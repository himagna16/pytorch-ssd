#!/usr/bin/env python3
"""Tests for kill_switch.py with a fake link and a fake clock. No hardware, no simulator, no cflib.

    ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/test_kill_switch.py

What this proves: the key handling (SPACE / ENTER stop, Ctrl-C stops, every other key does
nothing, q quits only after a stop), the watchdog schedule (first ping at once, then every
0.1 s, none after a stop), the stop repeats, link loss, a dead link that raises, and the CLI's
exit codes. What it cannot prove: that the drone obeys. The CrazySim run in
docs/sim_results/2026-10-01-flight-modes/ covers the cflib plumbing; only hardware covers the rest.
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kill_switch as K                                         # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


class FakeLink:
    def __init__(self, fail=False, locked_after_stop=True, protocol=12):
        self.events = []
        self.fail = fail
        self.locked_after_stop = locked_after_stop
        self.protocol = protocol
        self.info = 0b0001000        # "can fly"
        self.opened = self.closed = False
        self.lost_cbs = []

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def on_lost(self, cb):
        self.lost_cbs.append(cb)

    def send_watchdog(self):
        if self.fail:
            raise OSError("radio gone")
        self.events.append("wd")

    def send_stop(self):
        if self.fail:
            raise OSError("radio gone")
        self.events.append("stop")
        if self.locked_after_stop:
            self.info |= 1 << K.BIT_LOCKED

    def supervisor_info(self):
        return self.info, 0.0


class Keys:
    """Scripted key source: a list of characters, None (no key this poll) or exceptions."""

    def __init__(self, script):
        self.script = list(script)

    def get(self, timeout):
        if not self.script:
            raise AssertionError("key script ran out (the loop should have ended)")
        k = self.script.pop(0)
        if isinstance(k, BaseException) or (isinstance(k, type) and issubclass(k, BaseException)):
            raise k
        return k


def make(link=None):
    clock = Clock()
    link = link or FakeLink()
    return K.KillSwitch(link, clock=clock, sleep=clock.sleep), link, clock


class TestKeys(unittest.TestCase):
    def test_classify(self):
        for ch in (" ", "\r", "\n"):
            self.assertEqual(K.classify_key(ch), "stop", repr(ch))
        for ch in ("q", "Q"):
            self.assertEqual(K.classify_key(ch), "quit")
        for ch in ("a", "x", "\x1b", "\t", "0", "s", "k", "", "\x7f"):
            self.assertIsNone(K.classify_key(ch), repr(ch))

    def test_space_and_enter_stop(self):
        for ch, name in ((" ", "SPACE"), ("\r", "ENTER"), ("\n", "ENTER")):
            ks, link, _ = make()
            ks.arm()
            self.assertEqual(ks.on_key(ch), "stop")
            self.assertTrue(ks.stopped)
            self.assertEqual(ks.stop_reason, f"key {name}")
            self.assertEqual(link.events.count("stop"), K.STOP_REPEATS)

    def test_other_keys_do_nothing(self):
        ks, link, _ = make()
        ks.arm()
        for ch in "abcxyz0123456789\x1b\t[]":
            self.assertIsNone(ks.on_key(ch))
        self.assertFalse(ks.stopped)
        self.assertNotIn("stop", link.events)

    def test_q_quits_only_after_a_stop(self):
        ks, link, _ = make()
        ks.arm()
        self.assertIsNone(ks.on_key("q"))            # no quitting while armed
        self.assertFalse(ks.stopped)
        ks.on_key(" ")
        self.assertEqual(ks.on_key("q"), "quit")

    def test_second_press_resends(self):
        ks, link, _ = make()
        ks.arm()
        ks.on_key(" ")
        ks.on_key("\r")
        self.assertEqual(link.events.count("stop"), 2 * K.STOP_REPEATS)
        self.assertEqual(ks.stop_reason, "key SPACE")  # the first reason is kept

    def test_ctrl_c_and_link_loss_stop(self):
        ks, link, _ = make()
        ks.arm()
        ks.on_interrupt()
        self.assertTrue(ks.stopped and ks.stop_reason == "Ctrl-C")
        ks, link, _ = make()
        ks.arm()
        ks.on_link_lost("Too many packets lost")
        self.assertTrue(ks.stopped)
        self.assertIn("link lost", ks.stop_reason)
        self.assertEqual(ks.link_lost, "Too many packets lost")
        self.assertEqual(link.events.count("stop"), K.STOP_REPEATS)


class TestWatchdog(unittest.TestCase):
    def test_schedule(self):
        ks, link, clock = make()
        self.assertFalse(ks.tick())                   # not armed: nothing
        ks.arm()
        self.assertEqual(link.events, ["wd"])         # first ping at once
        self.assertFalse(ks.tick())                   # not due yet
        clock.t += K.WATCHDOG_PERIOD_S - 1e-6
        self.assertFalse(ks.tick())
        clock.t += 2e-6
        self.assertTrue(ks.tick())
        for _ in range(100):                          # 2 s at 20 ms polling
            clock.t += 0.02
            ks.tick()
        self.assertGreaterEqual(ks.pings, 21)
        self.assertLessEqual(ks.pings, 22)
        # the longest gap between pings stays far below the firmware's 1.0 s
        self.assertLess(K.WATCHDOG_PERIOD_S * 5, K.FIRMWARE_WATCHDOG_TIMEOUT_S)

    def test_no_pings_after_stop(self):
        ks, link, clock = make()
        ks.arm()
        ks.on_key(" ")
        n = link.events.count("wd")
        for _ in range(50):
            clock.t += 0.05
            self.assertFalse(ks.tick())
        self.assertEqual(link.events.count("wd"), n)

    def test_dead_link_does_not_raise(self):
        ks, link, clock = make(FakeLink(fail=True))
        ks.arm()
        clock.t += 0.2
        self.assertFalse(ks.tick())
        self.assertTrue(ks.stop("key SPACE"))
        self.assertEqual(ks.stops_sent, 0)
        self.assertTrue(any("failed" in e for e in ks.errors))

    def test_stop_spacing(self):
        ks, link, clock = make()
        t0 = clock.t
        ks.stop("x")
        self.assertAlmostEqual(clock.t - t0, (K.STOP_REPEATS - 1) * K.STOP_GAP_S)


class TestRunLoop(unittest.TestCase):
    def run_keys(self, script, link=None):
        ks, link, clock = make(link)
        out = io.StringIO()
        code = K.run(ks, link, "udp://test", Keys(script), out=out, color=False, redraw_s=0.0,
                     confirm_s=0.0, clear=False)
        return code, ks, link, out.getvalue()

    def test_space_then_q(self):
        code, ks, link, text = self.run_keys([None, "a", " ", None, "q"])
        self.assertEqual(code, 0)
        self.assertEqual(ks.stop_reason, "key SPACE")
        self.assertIn("EMERGENCY STOP SENT", text)
        self.assertIn("LOCKED", text)
        self.assertIn("KILL SWITCH ARMED", text)
        self.assertIn("FALLS", text)

    def test_ctrl_c_stops_and_exits(self):
        code, ks, link, text = self.run_keys([None, KeyboardInterrupt])
        self.assertEqual(code, 0)
        self.assertEqual(ks.stop_reason, "Ctrl-C")
        self.assertEqual(link.events.count("stop"), K.STOP_REPEATS)

    def test_sigterm_stops(self):
        code, ks, link, _ = self.run_keys([None, K.Abort])
        self.assertTrue(ks.stopped)
        self.assertIn("SIGTERM", ks.stop_reason)

    def test_crash_in_loop_still_stops(self):
        with self.assertRaises(RuntimeError):
            self.run_keys([None, RuntimeError("bug")])

    def test_crash_in_loop_sends_stop(self):
        ks, link, clock = make()
        try:
            K.run(ks, link, "udp://test", Keys([RuntimeError("bug")]), out=io.StringIO(), color=False,
                  redraw_s=0.0, confirm_s=0.0, clear=False)
        except RuntimeError:
            pass
        self.assertTrue(ks.stopped)
        self.assertEqual(ks.stop_reason, "kill switch exiting")
        self.assertEqual(link.events.count("stop"), K.STOP_REPEATS)

    def test_unconfirmed_lock_exit_1(self):
        code, ks, link, _ = self.run_keys([" ", "q"], link=FakeLink(locked_after_stop=False))
        self.assertEqual(code, 1)


class TestCli(unittest.TestCase):
    def test_main_with_fake_link(self):
        links = []

        def mk(uri):
            links.append(FakeLink())
            links[-1].uri = uri
            return links[-1]

        out = io.StringIO()
        code = K.main(["--uri", "udp://127.0.0.1:19850", "--no-color"], make_link=mk,
                      keys=Keys([None, "\n", "q"]), out=out)
        self.assertEqual(code, 0)
        self.assertEqual(links[0].uri, "udp://127.0.0.1:19850")
        self.assertTrue(links[0].opened and links[0].closed)
        self.assertIn("stop", links[0].events)

    def test_link_loss_via_callback(self):
        link = FakeLink()
        out = io.StringIO()

        class LoseThenQuit(Keys):
            def get(self, timeout):
                k = super().get(timeout)
                if k == "LOSE":
                    for cb in link.lost_cbs:
                        cb("Too many packets lost")
                    return None
                return k

        code = K.main(["--uri", "radio://0/80/2M/E7E7E7E709", "--no-color"], make_link=lambda uri: link,
                      keys=LoseThenQuit([None, "LOSE", None, "q"]), out=out)
        self.assertIn("LINK LOST", out.getvalue())
        self.assertIn("stop", link.events)
        self.assertEqual(code, 0)

    def test_bad_uri_and_connect_failure(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            K.main(["--uri", "tcp://x"], make_link=lambda u: FakeLink(), keys=Keys([]), out=io.StringIO())

        class Fails(FakeLink):
            def open(self):
                raise ConnectionError("no answer")

        out = io.StringIO()
        code = K.main(["--uri", "usb://0"], make_link=lambda u: Fails(), keys=Keys([]), out=out)
        self.assertEqual(code, 2)
        self.assertIn("NOT protecting", out.getvalue())

    def test_default_uri(self):
        self.assertEqual(K.DEFAULT_URI, "radio://0/80/2M/E7E7E7E709")
        for u in ("radio://0/80/2M/E7E7E7E709", "usb://0", "udp://127.0.0.1:19850"):
            self.assertEqual(K.check_uri(u), u)

    def test_decode_info(self):
        self.assertIn("LOCKED", K.decode_info(1 << K.BIT_LOCKED))
        self.assertTrue(K.is_locked(0x48))
        self.assertFalse(K.is_locked(0x08))
        self.assertFalse(K.is_locked(None))


if __name__ == "__main__":
    unittest.main(verbosity=1)

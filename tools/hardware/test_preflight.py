#!/usr/bin/env python3
"""Tests for preflight.py, with a fake drone. No hardware, no simulator, a second or two.

    ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/test_preflight.py

Any venv works for the fake-drone tests. The two tests that check the write
guards on a REAL cflib Crazyflie object are skipped if cflib is not installed
(cfloaderenv, trainenv and crazysimenv all have it).

What this proves: every deck combination, a flat battery, a firmware with
missing TOC groups and a failed connection all produce a sensible checklist and
a JSON file, and nothing in the tool can call a cflib method that writes to the
drone. What it cannot prove: that a real drone's TOC looks like the fake one.
The live run against CrazySim covers the cflib plumbing; only real hardware
covers the rest.
"""
import ast
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import preflight as P                                           # noqa: E402

HAVE_CFLIB = importlib.util.find_spec("cflib") is not None

# A trimmed copy of what the real firmware's TOC exposes (names checked against
# crazyflie-firmware in the CrazySim image, commit aa6571dc, 2026-04-03).
DECKS_ALL_ABSENT = {"bcAI": "0", "bcLighthouse4": "0", "bcFlow2": "0", "bcZRanger2": "0",
                    "bcMultiranger": "0", "bcUSD": "0"}
LH_LOG = {"status": "uint8_t", "bsReceive": "uint16_t", "bsActive": "uint16_t",
          "bsAvailable": "uint16_t", "bsCalVal": "uint16_t", "bsGeoVal": "uint16_t",
          "bsCalCon": "uint16_t", "bsCalUd": "uint16_t", "comSync": "uint8_t",
          "posRt": "float", "estBs0Rt": "float", "estBs1Rt": "float",
          "x": "float", "y": "float", "z": "float", "delta": "float"}


class FakeLink:
    """Implements exactly the methods run_preflight() and main() use."""

    def __init__(self, uri="usb://0", decks=None, params=None, log_toc=None, samples=None,
                 eeprom=None, tag="2025.02", device="CF21", protocol=9, deck_mems=None,
                 open_error=None, sample_raises=None):
        self.uri = uri
        self.params = {"firmware": {"revision0": "2858775004", "revision1": "18015", "modified": "0"},
                       "cpu": {"id0": "1", "id1": "2", "id2": "3"},
                       "deck": dict(DECKS_ALL_ABSENT if decks is None else decks)}
        if params is not None:
            self.params = params
        self.ltoc = log_toc if log_toc is not None else {
            "pm": {"vbat": "float", "state": "int8_t", "batteryLevel": "uint8_t"},
            "stateEstimate": {"x": "float", "y": "float", "z": "float"},
            "radio": {"rssi": "uint8_t"}}
        self.samples = samples or {}
        self.eeprom = eeprom
        self.tag, self.device, self.protocol = tag, device, protocol
        self.deck_mems = deck_mems or []
        self.open_error = open_error
        self.sample_raises = sample_raises
        self.closed = False
        self.sampled_vars = None
        self.guarded = ["commander.send_setpoint"]

    def open(self):
        if self.open_error:
            raise P.ConnectError(P.explain_connect_error(self.uri, self.open_error))
        return 1.23

    def wait_params(self):
        return True

    def close(self):
        self.closed = True

    def param_toc(self):
        return {g: sorted(v) for g, v in self.params.items()}

    def param_value(self, name):
        g, _, n = name.partition(".")
        return self.params.get(g, {}).get(n)

    def log_toc(self):
        return self.ltoc

    def protocol_version(self):
        return self.protocol

    def platform_query(self, cmd):
        return {1: self.tag, 2: self.device}[cmd]

    def read_eeprom(self):
        return self.eeprom

    def read_deck_memories(self):
        return self.deck_mems

    def sample(self, var_types, seconds, period_ms=100):
        if self.sample_raises:
            raise self.sample_raises
        self.sampled_vars = dict(var_types)
        return {k: list(self.samples.get(k, [])) for k in var_types}, []


def battery(v=4.05, state=0, n=20):
    return {"pm.vbat": [v] * n, "pm.state": [state] * n}


def lighthouse_samples(status=2, rx=0b11, active=0b11, cal=0b11, geo=0b11, sync=1,
                       pos_noise=0.0005, n=40):
    s = {"lighthouse.status": [status] * n, "lighthouse.bsReceive": [rx] * n,
         "lighthouse.bsActive": [active] * n, "lighthouse.bsAvailable": [rx] * n,
         "lighthouse.bsCalVal": [cal] * n, "lighthouse.bsGeoVal": [geo] * n,
         "lighthouse.comSync": [sync] * n, "lighthouse.posRt": [30.0] * n}
    for ax, c in zip("xyz", (0.5, -0.2, 0.03)):
        s[f"stateEstimate.{ax}"] = [c + (pos_noise if i % 2 else -pos_noise) for i in range(n)]
    return s


def with_lh_params(link, system_type="2"):
    link.params["lighthouse"] = {"systemType": system_type, "method": "1", "bsCalibReset": "0"}
    link.ltoc["lighthouse"] = dict(LH_LOG)
    return link


def run(link, **kw):
    return P.run_preflight(link, seconds=0, log=lambda *_: None, **kw)


class DeckCombinations(unittest.TestCase):

    def test_no_decks(self):
        r = run(FakeLink(samples=battery()))
        C = r["checks"]
        self.assertEqual(C["decks"]["summary"], "no decks detected")
        self.assertEqual(C["decks"]["details"]["present"], [])
        for k in ("lighthouse", "aideck", "uart_conflict"):
            self.assertEqual(C[k]["status"], P.SKIP, k)
        self.assertEqual(P.overall(r), P.OK)

    def test_ai_only(self):
        link = FakeLink(decks={**DECKS_ALL_ABSENT, "bcAI": "1"}, samples=battery())
        C = run(link)["checks"]
        self.assertEqual(C["decks"]["details"]["present"], ["bcAI"])
        self.assertEqual(C["aideck"]["status"], P.OK)
        self.assertIn("192.168.4.1:5000", C["aideck"]["summary"])
        self.assertIn("normal", C["aideck"]["summary"])     # no CPX params is normal
        self.assertEqual(C["lighthouse"]["status"], P.SKIP)
        self.assertEqual(C["uart_conflict"]["status"], P.SKIP)
        # no lighthouse vars sampled when there is no lighthouse deck
        self.assertFalse(any(v.startswith("lighthouse.") for v in link.sampled_vars))

    def test_ai_cpx_params_are_listed(self):
        link = FakeLink(decks={**DECKS_ALL_ABSENT, "bcAI": "1"}, samples=battery())
        link.params["cpx"] = {"wifiMode": "1"}
        C = run(link)["checks"]
        self.assertEqual(C["aideck"]["details"]["cpx_wifi_params"], ["cpx.wifiMode"])

    def test_lighthouse_only_working(self):
        link = with_lh_params(FakeLink(decks={**DECKS_ALL_ABSENT, "bcLighthouse4": "1"},
                                       samples={**battery(), **lighthouse_samples()}))
        C = run(link)["checks"]
        lh = C["lighthouse"]
        self.assertEqual(lh["status"], P.OK, lh["summary"])
        self.assertIn("V2", lh["summary"])
        self.assertIn("working", lh["summary"])
        lines = lh["details"]["base_stations"]
        self.assertEqual(len(lines), 2)
        self.assertIn("base station 1: seen, calibrated, geometry OK, in use for position", lines[0])
        self.assertAlmostEqual(lh["details"]["stats"]["position_std_mm_max"], 0.5, places=2)
        self.assertEqual(C["uart_conflict"]["status"], P.SKIP)
        # the lighthouse vars were chosen from the TOC, including the ones not in our list
        self.assertIn("lighthouse.bsGeoVal", link.sampled_vars)
        self.assertIn("stateEstimate.z", link.sampled_vars)
        self.assertNotIn("lighthouse.delta", link.sampled_vars)

    def test_lighthouse_geometry_missing(self):
        s = {**battery(), **lighthouse_samples(status=1, active=0, geo=0b01)}
        link = with_lh_params(FakeLink(decks={**DECKS_ALL_ABSENT, "bcLighthouse4": "1"}, samples=s))
        lh = run(link)["checks"]["lighthouse"]
        self.assertEqual(lh["status"], P.WARN)
        self.assertIn("geometry estimation", lh["summary"])
        self.assertIn("geometry MISSING", lh["details"]["base_stations"][1])
        self.assertIn("geometry OK", lh["details"]["base_stations"][0])

    def test_lighthouse_nothing_received_mentions_v1(self):
        s = {**battery(), **lighthouse_samples(status=0, rx=0, active=0, cal=0, geo=0)}
        link = with_lh_params(FakeLink(decks={**DECKS_ALL_ABSENT, "bcLighthouse4": "1"}, samples=s))
        lh = run(link)["checks"]["lighthouse"]
        self.assertEqual(lh["status"], P.WARN)
        self.assertIn("systemType must be 1", lh["summary"])
        self.assertIn("not here", lh["summary"])

    def test_both_decks_healthy(self):
        link = with_lh_params(FakeLink(decks={**DECKS_ALL_ABSENT, "bcAI": "1", "bcLighthouse4": "1"},
                                       samples={**battery(), **lighthouse_samples()}))
        r = run(link, gap8_state="running")
        uc = r["checks"]["uart_conflict"]
        self.assertEqual(uc["status"], P.INFO)
        self.assertTrue(uc["details"]["applicable"])
        m = uc["details"]["metrics"]
        self.assertEqual(m["gap8_state"], "running")
        self.assertEqual(m["comSync_fraction"], 1.0)
        self.assertEqual(m["status2_fraction"], 1.0)
        self.assertEqual(m["posRt_mean_hz"], 30.0)
        self.assertIn("UNVERIFIED", uc["summary"])
        text = P.render_report({**r, "started": "t"})
        self.assertIn("UART1 check", text)
        self.assertIn("crazyflie_ssd/Makefile line 4", text)
        self.assertIn("UART2", text)

    def test_both_decks_with_symptoms(self):
        s = {**battery(), **lighthouse_samples(pos_noise=0.05)}
        s["lighthouse.comSync"] = [1, 0] * 20
        s["lighthouse.status"] = [2, 1] * 20
        link = with_lh_params(FakeLink(decks={**DECKS_ALL_ABSENT, "bcAI": "1", "bcLighthouse4": "1"},
                                       samples=s))
        uc = run(link)["checks"]["uart_conflict"]
        self.assertEqual(uc["status"], P.WARN)
        self.assertEqual(len(uc["details"]["symptoms"]), 3, uc["details"]["symptoms"])
        self.assertIn("in sync only 50%", uc["summary"])

    def test_deck_attached_but_driver_not_started(self):
        link = FakeLink(decks={**DECKS_ALL_ABSENT}, samples=battery(),
                        deck_mems=[{"name": "bcAI", "vid": 0xBC, "pid": 0x12},
                                   {"name": "bcWeird", "vid": 0xBC, "pid": 0x99}])
        d = run(link)["checks"]["decks"]
        self.assertEqual(d["status"], P.WARN)
        self.assertTrue(any("did not start" in n for n in d["details"]["notes"]))
        self.assertTrue(any("no driver" in n for n in d["details"]["notes"]))


class Battery(unittest.TestCase):

    def test_low(self):
        c = run(FakeLink(samples=battery(3.62)))["checks"]["battery"]
        self.assertEqual(c["status"], P.WARN)
        self.assertIn("charge before a session", c["summary"])
        self.assertIn("350 mAh", c["summary"])
        self.assertIn("5-7 minutes", c["summary"])

    def test_flat_fails_and_exit_code_is_1(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.json"
            buf = io.StringIO()
            code = P.main(["--uri", "usb://0", "--out", str(out), "--seconds", "0"],
                          make_link=lambda u: FakeLink(uri=u, samples=battery(3.2)), out=buf)
            self.assertEqual(code, 1)
            rep = json.loads(out.read_text())
            self.assertEqual(rep["checks"]["battery"]["status"], P.FAIL)
            self.assertEqual(rep["overall"], P.FAIL)
            self.assertIn("FLAT", buf.getvalue())

    def test_low_power_state_fails(self):
        c = run(FakeLink(samples=battery(3.5, state=3)))["checks"]["battery"]
        self.assertEqual(c["status"], P.FAIL)

    def test_charging_is_ok_with_caveat(self):
        c = run(FakeLink(samples=battery(3.9, state=1)))["checks"]["battery"]
        self.assertEqual(c["status"], P.OK)
        self.assertIn("charging", c["summary"])
        self.assertIn("reads higher", c["summary"])

    def test_no_battery_reading(self):
        c = run(FakeLink(samples={}))["checks"]["battery"]
        self.assertEqual(c["status"], P.WARN)
        c = run(FakeLink(samples=battery(0.4)))["checks"]["battery"]
        self.assertIn("not a LiPo", c["summary"])


class MissingToc(unittest.TestCase):

    def test_bare_firmware_does_not_crash(self):
        link = FakeLink(params={}, log_toc={}, tag=None, device=None, protocol=None)
        r = run(link)
        C = r["checks"]
        self.assertEqual(C["firmware"]["status"], P.WARN)
        self.assertEqual(C["decks"]["status"], P.WARN)
        self.assertIn("no deck.* parameters", C["decks"]["summary"])
        self.assertEqual(C["battery"]["status"], P.WARN)
        self.assertEqual(link.sampled_vars, None)             # nothing to sample, nothing sampled
        P.render_report({**r, "started": "t"})                 # renders without crashing

    def test_lighthouse_deck_without_log_group(self):
        link = FakeLink(decks={"bcLighthouse4": "1"}, samples=battery())
        link.ltoc.pop("lighthouse", None)
        lh = run(link)["checks"]["lighthouse"]
        self.assertEqual(lh["status"], P.WARN)
        self.assertIn("no lighthouse log group", lh["summary"])

    def test_lighthouse_with_only_status(self):
        link = FakeLink(decks={"bcLighthouse4": "1"},
                        samples={**battery(), "lighthouse.status": [2] * 5})
        link.ltoc["lighthouse"] = {"status": "uint8_t"}
        lh = run(link)["checks"]["lighthouse"]
        self.assertEqual(lh["status"], P.OK)
        self.assertEqual(lh["details"]["base_stations"], [])
        self.assertIsNone(lh["details"]["system_type"])

    def test_unreadable_deck_value(self):
        link = FakeLink(decks={"bcAI": None, "bcFlow2": "1"}, samples=battery())
        d = run(link)["checks"]["decks"]
        self.assertIn("could not read: bcAI", d["summary"])

    def test_link_method_raising_is_recorded_not_fatal(self):
        link = FakeLink(samples=battery())

        def boom():
            raise TimeoutError("EEPROM went quiet")
        link.read_eeprom = boom
        r = run(link)
        self.assertTrue(any("EEPROM went quiet" in e for e in r["errors"]))
        self.assertEqual(r["checks"]["radio"]["status"], P.INFO)


class Radio(unittest.TestCase):

    def test_eeprom_factory_address(self):
        link = FakeLink(samples=battery(), eeprom={"version": 1, "radio_channel": 80, "radio_speed": 2,
                                                   "pitch_trim": 0.0, "roll_trim": 0.0,
                                                   "radio_address": 0xE7E7E7E7E7})
        c = run(link)["checks"]["radio"]
        self.assertEqual(c["status"], P.OK)
        self.assertIn("radio://0/80/2M/E7E7E7E7E7", c["summary"])
        self.assertIn("factory default", c["summary"])
        self.assertIn("different addresses", c["summary"])

    def test_second_drone_same_address_warns(self):
        link = FakeLink(samples=battery(), eeprom={"radio_channel": 80, "radio_speed": 2,
                                                   "radio_address": 0xE7E7E7E7E7})
        other = [("0000000900000009000000A0", "E7E7E7E7E7", "/x/20260922-100000.json")]
        c = run(link, other_runs=other)["checks"]["radio"]
        self.assertEqual(c["status"], P.WARN)
        self.assertIn("ANOTHER drone", c["summary"])
        self.assertIn("never changes it", c["summary"])

    def test_same_drone_again_does_not_warn(self):
        link = FakeLink(samples=battery(), eeprom={"radio_channel": 80, "radio_speed": 2,
                                                   "radio_address": 0xE7E7E7E7E7})
        serial = "000000010000000200000003"
        c = run(link, other_runs=[(serial, "E7E7E7E7E7", "/x/a.json")])["checks"]["radio"]
        self.assertEqual(c["status"], P.OK)

    def test_radio_uri_without_eeprom(self):
        link = FakeLink(uri="radio://0/60/2M/E7E7E7E701", samples=battery())
        c = run(link)["checks"]["radio"]
        self.assertIn("channel 60", c["summary"])
        self.assertIn("E7E7E7E701", c["summary"])
        self.assertIn("radio.rssi", link.sampled_vars)

    def test_load_other_runs_reads_previous_json(self):
        with tempfile.TemporaryDirectory() as d:
            out1 = Path(d) / "a.json"
            P.main(["--uri", "usb://0", "--out", str(out1), "--seconds", "0"],
                   make_link=lambda u: FakeLink(uri=u, samples=battery(), eeprom={
                       "radio_channel": 80, "radio_speed": 2, "radio_address": 0xE7E7E7E7E7}),
                   out=io.StringIO())
            runs = P.load_other_runs(d)
            self.assertEqual(runs, [("000000010000000200000003", "E7E7E7E7E7", str(out1))])


class Connection(unittest.TestCase):

    def test_connection_failure_message_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "fail.json"
            buf = io.StringIO()
            code = P.main(["--uri", "usb://0", "--out", str(out)],
                          make_link=lambda u: FakeLink(uri=u, open_error="Too many packets lost"),
                          out=buf)
            self.assertEqual(code, 2)
            text = buf.getvalue()
            self.assertIn("DATA cable", text)
            self.assertIn("cfclient", text)
            self.assertIn("battery is plugged in", text)
            rep = json.loads(out.read_text())
            self.assertEqual(rep["checks"]["link"]["status"], P.FAIL)
            self.assertEqual(rep["overall"], P.FAIL)
            self.assertTrue(rep["read_only"])

    def test_nothing_found_by_scan(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "none.json"
            buf = io.StringIO()
            code = P.main(["--out", str(out)], make_link=lambda u: FakeLink(uri=u),
                          scan=lambda: [], out=buf)
            self.assertEqual(code, 2)
            self.assertIn("No Crazyflie found", buf.getvalue())
            self.assertIn("USB-A adapter", buf.getvalue())
            self.assertEqual(buf.getvalue().count("Saved:"), 1)

    def test_scan_prefers_usb_then_radio_and_falls_back(self):
        scan = lambda: [["radio://0/80/2M/E7E7E7E7E7", ""], ["udp://127.0.0.1:19850", ""],  # noqa: E731
                        ["usb://0", ""]]
        self.assertEqual(P.discover_uris(scan), ["usb://0", "radio://0/80/2M/E7E7E7E7E7"])
        tried = []

        def make(u):
            tried.append(u)
            return FakeLink(uri=u, samples=battery(),
                            open_error="Could not open USB" if u.startswith("usb") else None)
        link, secs, attempts = P.connect_first(P.discover_uris(scan), make, log=lambda *_: None)
        self.assertEqual(tried, ["usb://0", "radio://0/80/2M/E7E7E7E7E7"])
        self.assertEqual(link.uri, "radio://0/80/2M/E7E7E7E7E7")
        self.assertFalse(attempts[0]["ok"])
        self.assertTrue(attempts[1]["ok"])

    def test_scan_exception_means_no_uris(self):
        def bad():
            raise OSError("libusb exploded")
        self.assertEqual(P.discover_uris(bad), [])

    def test_traceback_is_trimmed_from_errors(self):
        raw = ("Error communicating with the Crazyflie\nException:[Errno 61] Connection refused\n\n"
               "Traceback (most recent call last):\n  File \"udpdriver.py\", line 285, in run\n")
        m = P.explain_connect_error("udp://127.0.0.1:19850", raw)
        self.assertNotIn("Traceback", m)
        self.assertIn("Connection refused", m)

    def test_explain_radio_errors(self):
        m = P.explain_connect_error("radio://0/80/2M/E7E7E7E7E7", "Cannot find a Crazyradio Dongle")
        self.assertIn("USB-A", m)
        m = P.explain_connect_error("radio://0/80/2M/E7E7E7E7E7", "Too many packets lost")
        self.assertIn("re-addressed", m)
        m = P.explain_connect_error("udp://127.0.0.1:19850", "timeout")
        self.assertIn("run_sim.sh", m)

    def test_ctrl_c_still_closes_link_and_saves(self):
        holder = {}

        def make(u):
            holder["link"] = FakeLink(uri=u, sample_raises=KeyboardInterrupt())
            return holder["link"]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "int.json"
            buf = io.StringIO()
            code = P.main(["--uri", "usb://0", "--out", str(out)], make_link=make, out=buf)
            self.assertEqual(code, 130)
            self.assertTrue(holder["link"].closed)
            rep = json.loads(out.read_text())
            self.assertTrue(rep["interrupted"])
            # checks finished before the Ctrl-C are kept
            self.assertIn("firmware", rep["checks"])
            self.assertIn("decks", rep["checks"])
            self.assertIn("nothing on the drone was changed", buf.getvalue())

    def test_compare_prints_side_by_side(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.json", Path(d) / "b.json"
            both = {**DECKS_ALL_ABSENT, "bcAI": "1", "bcLighthouse4": "1"}
            P.main(["--uri", "usb://0", "--out", str(a), "--gap8", "running"],
                   make_link=lambda u: with_lh_params(FakeLink(
                       uri=u, decks=both, samples={**battery(), **lighthouse_samples(sync=0)})),
                   out=io.StringIO())
            buf = io.StringIO()
            P.main(["--uri", "usb://0", "--out", str(b), "--gap8", "no-deck", "--compare", str(a)],
                   make_link=lambda u: with_lh_params(FakeLink(
                       uri=u, decks={**DECKS_ALL_ABSENT, "bcLighthouse4": "1"},
                       samples={**battery(), **lighthouse_samples()})),
                   out=buf)
            text = buf.getvalue()
            self.assertIn("Compared with", text)
            row = next(line for line in text.splitlines() if "comSync fraction" in line)
            self.assertEqual(row.split()[-2:], ["0.0", "1.0"])


class Helpers(unittest.TestCase):

    def test_git_revision_matches_sitl(self):
        # the CrazySim firmware reports these and is built from commit aa6571dc465f...
        self.assertEqual(P.firmware_git_revision("2858775004", "18015"), "aa6571dc465f")
        self.assertIsNone(P.firmware_git_revision(None, "1"))

    def test_bits(self):
        self.assertEqual(P.bits(0b101), [1, 3])
        self.assertEqual(P.bits(0), [])
        self.assertEqual(P.bits(None), [])

    def test_chunks_fit_one_packet(self):
        vs = [(f"v{i}", "float") for i in range(10)] + [("s", "uint8_t"), ("m", "uint16_t")]
        blocks = P.chunk_log_vars(vs)
        for b in blocks:
            size = sum(P.LOG_SIZES[dict(vs)[n]] for n in b)
            self.assertLessEqual(size, 26)
        self.assertEqual(sum(len(b) for b in blocks), len(vs))

    def test_parse_radio_uri(self):
        self.assertEqual(P.parse_radio_uri("radio://0/80/2M/e7e7e7e7e7"),
                         {"dongle": "0", "channel": 80, "speed": "2M", "address": "E7E7E7E7E7"})
        self.assertIsNone(P.parse_radio_uri("usb://0"))


class ReadOnly(unittest.TestCase):
    """The whole point of the tool: it must never be able to change the drone."""

    FORBIDDEN_CALLS = {"set_value", "set_value_raw", "send_setpoint", "send_hover_setpoint",
                       "send_position_setpoint", "send_velocity_world_setpoint",
                       "send_zdistance_setpoint", "send_notify_setpoint_stop", "send_stop_setpoint",
                       "takeoff", "land", "go_to", "start_trajectory", "send_arming_request",
                       "send_crash_recovery_request", "set_continous_wave", "write", "write_data",
                       "erase", "persistent_store", "send_extpos", "send_extpose",
                       "send_emergency_stop", "reset_to_bootloader", "reset_to_firmware",
                       "send_lh_persist_data_packet", "send_user_notification"}

    def test_source_never_calls_a_write_method(self):
        tree = ast.parse((HERE / "preflight.py").read_text())
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in self.FORBIDDEN_CALLS:
                    bad.append((node.lineno, node.func.attr))
        self.assertEqual(bad, [], f"preflight.py calls write-capable methods: {bad}")

    def test_platform_query_refuses_non_version_commands(self):
        link = P.CflibLink("usb://0")
        for cmd in (0, 3, 99):
            with self.assertRaises(P.ReadOnlyViolation):
                link.platform_query(cmd)

    def test_guards_on_fake_object(self):
        class Obj:
            def send_setpoint(self, *a):
                return "moved"

            def set_value(self, *a):
                return "wrote"

            def get_value(self, *a):
                return "read"

        class CF:
            commander = Obj()
            param = Obj()
        cf = CF()
        cf.commander, cf.param = Obj(), Obj()
        g = P.install_write_guards(cf)
        self.assertIn("commander.send_setpoint", g)
        self.assertIn("param.set_value", g)
        with self.assertRaises(P.ReadOnlyViolation):
            cf.commander.send_setpoint(0, 0, 0, 10000)
        with self.assertRaises(P.ReadOnlyViolation):
            cf.param.set_value("x.y", 1)
        self.assertEqual(cf.param.get_value("x.y"), "read")

    @unittest.skipUnless(HAVE_CFLIB, "cflib not installed in this venv")
    def test_guards_on_real_cflib_crazyflie(self):
        from cflib.crazyflie import Crazyflie
        cf = Crazyflie()                       # no link opened; nothing is sent anywhere
        guarded = P.install_write_guards(cf)
        must = ["commander.send_setpoint", "commander.send_hover_setpoint",
                "high_level_commander.takeoff", "high_level_commander.go_to",
                "supervisor.send_arming_request", "platform.send_arming_request",
                "platform.set_continous_wave", "param.set_value", "param.set_value_raw",
                "mem.write", "loc.send_extpos", "extpos.send_extpos"]
        for name in must:
            self.assertIn(name, guarded)
            obj, meth = name.split(".")
            with self.assertRaises(P.ReadOnlyViolation, msg=name):
                getattr(getattr(cf, obj), meth)(*([0] * 4))
        # reading is untouched
        self.assertTrue(callable(cf.param.get_value))
        self.assertTrue(callable(cf.platform.get_protocol_version))

    @unittest.skipUnless(HAVE_CFLIB, "cflib not installed in this venv")
    def test_cflib_version_constants_match(self):
        from cflib.crazyflie import platformservice as ps
        self.assertEqual(ps.VERSION_COMMAND, P.CflibLink.VERSION_CHANNEL)
        self.assertEqual(ps.VERSION_GET_FIRMWARE, P.CflibLink.VERSION_GET_FIRMWARE)


if __name__ == "__main__":
    unittest.main(verbosity=1)

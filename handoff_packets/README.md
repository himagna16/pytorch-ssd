# DroneRS onboarding packets

Send these PDFs to the new team:

- `DroneRS_Frontend_Firmware_Onboarding.pdf`
- `DroneRS_Backend_Model_Onboarding.pdf`

The editable LaTeX sources are `frontend_onboarding.tex`,
`backend_onboarding.tex`, and `onboarding_style.tex`.

Build both PDFs from this directory with:

```bash
bash ./build_pdfs.sh
```

The packets assume the handoff baseline is available on the remote
`unstable` branch at commit `b11e9da` or newer. Confirm that commit has been
pushed before distributing them.

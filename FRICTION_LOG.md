# Friction log

Worth up to +10% of the judging score. Add an entry whenever something about Fire TV, Vega OS,
Bedrock or the docs slows you down: what you tried, what you expected, what happened, how long it
cost, and what would have helped.

| Date | Area | What happened | Time lost | Suggestion |
|---|---|---|---|---|
| 2026-09-19 | Fire TV / voice | To verify: can a third-party Fire TV app get speech input? The remote's mic button goes to Alexa. The app tries `SpeechRecognizer` and falls back to the on-screen keyboard. | | |
| 2026-09-19 | Fire OS emulator | No Fire OS image in the Android SDK manager. We develop on the stock Android TV API 30 image (the Android 11 base of Fire OS 8), so Fire-specific behaviour (Alexa mic routing, Amazon keyboard, Fire launcher banner) can't be tested without hardware. | | An official Fire OS emulator image, or a doc listing what differs from stock Android TV. |
| 2026-09-19 | Fire TV remote / Menu key | The ☰ key is the only free remote button for an in-app overlay (the mic goes to Alexa, OK and D-pad belong to the player). It isn't clear whether apps may rely on it for primary features. | | Guidance in the Fire TV UX docs on which keys third-party apps may use for overlays. |
| 2026-09-19 | Bedrock IAM | To verify: which IAM actions the Bedrock Messages-API (Mantle) endpoint needs. `template.yaml` grants `bedrock-mantle:*` plus `bedrock:InvokeModel*` for now. | | |

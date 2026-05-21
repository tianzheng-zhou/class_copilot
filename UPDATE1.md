# UPDATE1

## Summary

This update adds a configurable no-output timeout for live transcription. If the backend does not produce any transcript text for the configured number of minutes, the current listening session is stopped and the frontend receives a structured error message.

## User-Facing Behavior

- A new setting is available in Settings -> Advanced Settings -> ASR & VAD Parameters:
  - `No-output Timeout (min)` / `转写无输出超时 (分钟)`
- Default value: `5.0` minutes.
- Set the value to `0` to disable this protection.
- When the timeout is reached:
  - The backend stops the current listening session.
  - The session is marked as interrupted.
  - The frontend receives an error event with code `transcript_no_output_timeout`.
  - The UI shows an error toast and the listening status changes to error/stopped.

## Failure Handling

If the timeout handling or session stop process itself fails:

- The backend logs the exception with a stack trace.
- The frontend receives an error event with code `stop_failed` when possible.
- The backend process exits to avoid leaving a broken listening session running in the background.

## Backend Changes

- Added runtime setting:
  - `transcript_no_output_timeout_minutes`
- Added the setting to the HTTP settings patch schema.
- Added an ASR pipeline watchdog task that checks transcript output activity.
- Updated session stop logic to be idempotent and to fail closed if cleanup fails.
- Added structured error details to backend WebSocket error events.

Key files:

- `class_copilot/application/settings.py`
- `class_copilot/api/schemas.py`
- `class_copilot/application/session.py`

## Frontend Changes

- Added the new setting to the TypeScript settings contract.
- Added the setting input to the advanced ASR settings section.
- Added frontend WebSocket error codes:
  - `transcript_no_output_timeout`
  - `stop_failed`
- Added Chinese and English labels for the new setting.

Key files:

- `frontend/src/api/types.ts`
- `frontend/src/components/settings/AsrParamsSection.tsx`
- `frontend/src/ws/messages.ts`
- `frontend/src/i18n/zh.ts`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/types.ts`

## Tests

Added coverage for:

- The default no-output timeout setting returned by `GET /api/settings`.
- Updating the no-output timeout through `PATCH /api/settings`.
- Stopping an active session and broadcasting `transcript_no_output_timeout` when no transcript output appears before the configured timeout.

Key files:

- `tests/test_http_api.py`
- `tests/test_ws.py`

## Verification

The following checks passed:

```powershell
C:\D\class_copilot\.venv\Scripts\python.exe -m pytest
npm run build
C:\D\class_copilot\.venv\Scripts\python.exe -m compileall class_copilot tests
```

Results:

- Backend tests: `13 passed`
- Frontend production build: successful
- Python compile check: successful

## Operational Note

If an older backend process is already running on `127.0.0.1:29037`, stop it and restart the app before testing this update. Otherwise the frontend may still be connected to the old backend code and the new setting may not appear.

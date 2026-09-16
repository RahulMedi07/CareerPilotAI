/**
 * Rules the UI shares with the backend.
 *
 * The backend is the one that enforces this -- a check in the browser is a
 * courtesy to the person typing, not a control, since anyone can call the API
 * directly. It lives here so the number appears once instead of being written
 * into a `minLength` and a help sentence separately and drifting apart.
 *
 * Must match `MIN_PASSWORD_LENGTH` in `backend/utils/auth.py`.
 */
export const MIN_PASSWORD_LENGTH = 8;

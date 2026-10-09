# Requirements Specification: Login Page

- Source: `agents/shared_context/user-story-login.md`
- Author: Alice (requirements analyst)
- Status: Draft 1, ready for tests

## 1. Summary

A registered user signs in with an email address and a passphrase-style password. The page checks the input format before it sends anything to the server, shows plain error messages, lets the user show or hide the password, and locks login for 5 seconds after 3 failed attempts in a row. A successful login takes the user to their personal page.

## 2. Glossary

| Term | Meaning |
|---|---|
| Login page | The page served at `/`. |
| Personal page | The page served at `/home`, shown only to a signed-in user. |
| Normalized email | The email with leading and trailing whitespace removed, converted to lowercase. |
| Failed attempt | A login request that passes format validation but whose email and password do not match a stored account. |
| Lock | The 5-second period after the 3rd consecutive failed attempt, during which login is refused. |
| Space | The ASCII space character U+0020 only. Tabs, newlines, and other whitespace are not spaces. |
| Word | A run of one or more characters that are not spaces. |

## 3. Validation rules

### 3.1 Email (VR-E)

The value is trimmed of leading and trailing whitespace, then it is valid only when all of these hold:

- VR-E1: it is not empty.
- VR-E2: it is at most 254 characters long.
- VR-E3: it contains exactly one `@`.
- VR-E4: the local part (before `@`) is 1 to 64 characters, uses only `A-Z a-z 0-9 . _ % + -`, does not start or end with `.`, and has no `..`.
- VR-E5: the domain (after `@`) has at least two labels separated by `.`; each label is 1 to 63 characters of `A-Z a-z 0-9 -` and does not start or end with `-`.
- VR-E6: the last label (top-level domain) is at least 2 letters and contains only letters `A-Z a-z`.

Reference regular expression (to be used together with the length limits in VR-E2 and VR-E4):

```
^[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$
```

Examples:

| Input | Valid? |
|---|---|
| `name@example.com` | yes |
| `  Name.Surname+tag@Mail.Example.co.id  ` | yes (trimmed; case does not matter) |
| `` (empty) or only spaces | no (empty) |
| `name@example` | no (no top-level domain) |
| `name.example.com` | no (no `@`) |
| `name@@example.com` | no (two `@`) |
| `.name@example.com` | no (local part starts with `.`) |
| `na..me@example.com` | no (`..`) |
| `name@-example.com` | no (label starts with `-`) |
| `name@example.c` | no (top-level domain shorter than 2) |
| `name@example.c0m` | no (top-level domain has a digit) |
| `name @example.com` | no (space inside) |

### 3.2 Password (VR-P)

The password is never trimmed or changed. It is valid only when all of these hold:

- VR-P1: it is not empty.
- VR-P2: it is at most 128 characters long.
- VR-P3: splitting it on spaces (U+0020) gives at least 3 non-empty words.
- VR-P4: it contains at least 2 spaces.

Since words are separated by spaces, VR-P3 implies VR-P4; both are listed because the story names both. Extra spaces (leading, trailing, or several in a row) are allowed and are part of the password.

Examples:

| Input | Valid? |
|---|---|
| `green apple house` | yes |
| `green apple house tree` | yes |
| `Gr33n! apple  house` | yes (two spaces in a row are allowed) |
| `green apple` | no (2 words) |
| `greenapplehouse` | no (1 word, no spaces) |
| `green  apple` | no (2 spaces but only 2 words) |
| `   ` (3 spaces) | no (no words) |
| `green\tapple\thouse` (tabs) | no (tabs are not spaces) |
| 129 characters | no (too long) |

## 4. Functional requirements

### Page and form

- **FR-1** The app serves the login page at `GET /`. It contains a form with an email field, a password field, a show/hide password button, a Login button, and a message area.
- **FR-2** The email field has the visible label "Email", `type="email"`, `autocomplete="username"`, and is required. Its placeholder is `name@example.com`.
- **FR-3** The password field has the visible label "Password", `autocomplete="current-password"`, and is required. On page load its `type` is `password` (characters masked).
- **FR-4** The page uses these element IDs so tests and code agree:

  | Element | ID |
  |---|---|
  | form | `login-form` |
  | email input | `email` |
  | email error text | `email-error` |
  | password input | `password` |
  | password error text | `password-error` |
  | show/hide button | `toggle-password` |
  | Login button | `login-button` |
  | form message area (credential errors, lock, server errors) | `form-message` |

### Show/hide password

- **FR-5** Clicking `toggle-password` while the password is hidden changes the password field `type` to `text`, sets the button text to "Hide" and its `aria-label` to "Hide password", and sets `aria-pressed="true"`.
- **FR-6** Clicking `toggle-password` while the password is shown changes the field `type` back to `password`, sets the button text to "Show", its `aria-label` to "Show password", and `aria-pressed="false"`.
- **FR-7** Toggling does not change the password value, does not submit the form (the button is `type="button"`), and works with the keyboard (Enter and Space).

### Client-side validation

- **FR-8** When the user submits the form (click Login or press Enter in a field), the page validates both fields with the rules in section 3 before sending any request. If any field is invalid, no request is sent and the field errors in FR-9 are shown. Both fields are checked and all errors are shown at once.
- **FR-9** Field error messages (shown in `email-error` / `password-error`):

  | Situation | Message |
  |---|---|
  | Email empty (VR-E1) | `Please enter your email address.` |
  | Email not empty but invalid (VR-E2..E6) | `Please enter a valid email address, for example name@example.com.` |
  | Password empty (VR-P1) | `Please enter your password.` |
  | Password not empty but invalid (VR-P2..P4) | `Your password must have at least 3 words separated by spaces, for example: green apple house.` |

- **FR-10** A field with an error gets `aria-invalid="true"`; after a failed validation, focus moves to the first invalid field. When the user changes a field's value, that field's error text is cleared and `aria-invalid` is removed.
- **FR-11** Client-side validation failures are not failed attempts and do not change the attempt count.

### Login request

- **FR-12** On valid input, the page sends `POST /api/login` with JSON body `{"email": "<as typed>", "password": "<as typed>"}`. The Login button is disabled while the request is in progress.
- **FR-13** The server repeats the validation in section 3. If the input is invalid it responds `422` with body `{"error": "validation_error", "fields": {"email": "<message>", "password": "<message>"}}` (only the invalid fields are listed, with the messages from FR-9). This does not count as a failed attempt.
- **FR-14** The server looks up the account by normalized email and compares the password exactly (case-sensitive, spaces included) against the stored hash.
- **FR-15** On success the server responds `200` with `{"ok": true, "redirect": "/home"}` and sets a session cookie. The page then navigates to `/home`.
- **FR-16** On wrong email or wrong password (when not locked and before the 3rd failure) the server responds `401` with `{"error": "invalid_credentials", "attempts_remaining": N}` where N is 2 after the 1st failure and 1 after the 2nd. The page shows in `form-message`: `Email or password is incorrect. You have N attempts left.` (use `1 attempt left` when N is 1). The response and message are the same whether the email exists or not.
- **FR-17** After a failed attempt the page keeps the email value, clears the password field, and moves focus to the password field.

### Attempt counting and lock

- **FR-18** The server counts consecutive failed attempts per normalized email, whether or not the account exists. The count is kept on the server, so reloading the page does not reset it.
- **FR-19** On the 3rd consecutive failed attempt the server starts a 5-second lock for that normalized email and responds `423` with `{"error": "locked", "retry_after": 5}` and the header `Retry-After: 5`.
- **FR-20** While the lock is active, every login request for that email is refused with `423`, `{"error": "locked", "retry_after": S}` and `Retry-After: S`, where S is the remaining whole seconds rounded up (1 to 5). The password is not checked, the request is not counted, and the lock is not extended. A correct password does not get in during the lock.
- **FR-21** When the page receives a `423`, it disables the Login button and shows in `form-message`: `Too many failed attempts. Please wait S seconds before trying again.` (`1 second` when S is 1). The number counts down once per second. The email and password fields stay editable; pressing Enter does not submit while locked.
- **FR-22** When the countdown reaches 0, the page re-enables the Login button and replaces the message with `You can try logging in again.`
- **FR-23** When the lock expires, the server resets the failed-attempt count for that email to 0, so the user again has 3 attempts.
- **FR-24** A successful login resets the failed-attempt count for that email to 0.
- **FR-25** Failed attempts do not expire on their own; the count is reset only by FR-23 or FR-24.

### Personal page

- **FR-26** `GET /home` with a valid session shows the personal page with the heading `Welcome, <email>` where `<email>` is the account's stored email.
- **FR-27** `GET /home` without a valid session redirects (`303`) to `/`.

### Other errors

- **FR-28** If the request fails because of a network error or any status other than 200, 401, 422, or 423, the page shows `Something went wrong. Please try again later.` in `form-message`, re-enables the Login button, and does not change the attempt count.

### Data

- **FR-29** Accounts are stored in SQLite with at least: id, email (unique, stored normalized), and password hash. The database setup creates a seed account for testing: email `user@example.com`, password `green apple house`.

## 5. Non-functional requirements

### Security

- **NFR-1** Passwords are stored only as salted hashes made with a slow key-derivation function from the Python standard library (`hashlib.scrypt` or `hashlib.pbkdf2_hmac` with at least 200,000 iterations). Plain-text passwords are never stored or logged.
- **NFR-2** Password comparison uses a constant-time function (`hmac.compare_digest`).
- **NFR-3** All SQL uses parameterized queries.
- **NFR-4** Credentials are sent only in the body of a `POST` request, never in the URL.
- **NFR-5** The error for a failed login does not say whether the email or the password was wrong (see FR-16).
- **NFR-6** The session cookie is `HttpOnly` and `SameSite=Lax`, and its value is a random token of at least 128 bits. `Secure` is set when served over HTTPS.
- **NFR-7** The lock is enforced by the server (FR-18 to FR-20); disabling the button in the browser is only for usability.
- **NFR-8** The server rejects request bodies with an email over 254 characters or a password over 128 characters with `422` (FR-13).

### Usability

- **NFR-9** All messages are in plain English, say what to do next, and use the exact text in this document.
- **NFR-10** The whole flow works with the keyboard alone: Tab order is email, password, show/hide, Login; Enter in either field submits.
- **NFR-11** The login request gets a response within 1 second on a local machine (excluding the lock).
- **NFR-12** The page works at viewport widths from 320 px to 1920 px without horizontal scrolling.

### Accessibility

- **NFR-13** Every input has a `<label>` linked by `for`/`id`; each field's error text is linked with `aria-describedby`.
- **NFR-14** `form-message` has `role="alert"` (or `aria-live="assertive"`) so screen readers announce errors and the lock. The countdown update in FR-21 must not be announced every second; only the first lock message and the FR-22 message are announced (for example by updating the visible number in an element with `aria-live="off"`).
- **NFR-15** Error messages are shown as text, not by colour alone. Text and controls meet WCAG 2.1 AA contrast (4.5:1 for normal text).
- **NFR-16** All controls have a visible focus indicator.
- **NFR-17** The page has `<html lang="en">` and a `<title>` of `Login`.

### Implementation constraints

- **NFR-18** Tech stack as in the team context: FastAPI back end serving the page, SQLite via `sqlite3`, plain HTML/CSS/JS with no build step.
- **NFR-19** The lock duration (5 s) and maximum attempts (3) are named constants in one place in the back end, so tests can rely on them.

## 6. Acceptance criteria

- **AC-1** (FR-1, FR-2, FR-3, NFR-17) Given I open `/`, when the page loads, then I see an Email field, a Password field with masked input, a Show button, and a Login button.
- **AC-2** (FR-8, FR-9, FR-11) Given the email field is empty, when I click Login, then I see `Please enter your email address.` and no request is sent.
- **AC-3** (FR-8, FR-9, VR-E) Given I enter `name@example` and a valid password, when I click Login, then I see `Please enter a valid email address, for example name@example.com.` and no request is sent.
- **AC-4** (FR-8, FR-9) Given a valid email and an empty password, when I click Login, then I see `Please enter your password.` and no request is sent.
- **AC-5** (FR-8, FR-9, VR-P) Given a valid email and the password `green apple`, when I click Login, then I see `Your password must have at least 3 words separated by spaces, for example: green apple house.` and no request is sent.
- **AC-6** (FR-8, FR-10) Given both fields are empty, when I click Login, then both field errors are shown, both fields have `aria-invalid="true"`, and focus is on the email field.
- **AC-7** (FR-3, FR-5) Given I typed a password, when I click Show, then the password is visible as plain text and the button reads Hide.
- **AC-8** (FR-6, FR-7) Given the password is visible, when I click Hide, then the password is masked again, the value is unchanged, and the form was not submitted.
- **AC-9** (FR-12, FR-14, FR-15, FR-26) Given the account `user@example.com` / `green apple house`, when I log in with ` USER@example.com ` and `green apple house`, then I am taken to `/home` and see `Welcome, user@example.com`.
- **AC-10** (FR-16, FR-17, FR-18, NFR-5) Given no failed attempts, when I log in with `user@example.com` and `red apple house`, then I see `Email or password is incorrect. You have 2 attempts left.`, the email is kept, and the password field is empty.
- **AC-11** (FR-16, NFR-5) Given no failed attempts, when I log in with an email that has no account, then I get the same response and message as AC-10.
- **AC-12** (FR-16, FR-18) Given 1 failed attempt, when I fail again, then I see `Email or password is incorrect. You have 1 attempt left.`
- **AC-13** (FR-19, FR-21) Given 2 failed attempts, when I fail a 3rd time, then the server responds `423` with `retry_after` 5, the Login button is disabled, and I see `Too many failed attempts. Please wait 5 seconds before trying again.` counting down each second.
- **AC-14** (FR-20, NFR-7) Given the lock is active, when a login request with the correct password is sent directly to `POST /api/login`, then it is refused with `423` and the lock is not extended.
- **AC-15** (FR-22, FR-23) Given the lock started, when 5 seconds have passed, then the Login button is enabled, I see `You can try logging in again.`, and I have 3 attempts again.
- **AC-16** (FR-23, FR-15) Given the lock has expired, when I log in with the correct password, then I reach `/home`.
- **AC-17** (FR-24) Given 2 failed attempts, when I log in successfully and then fail once, then I see `You have 2 attempts left.` (the count was reset).
- **AC-18** (FR-13, FR-11) Given no failed attempts, when a request with an invalid email or password format is sent directly to `POST /api/login`, then it gets `422` with the field messages and the attempt count stays 0.
- **AC-19** (FR-27) Given I am not signed in, when I open `/home`, then I am redirected to `/`.
- **AC-20** (FR-18) Given 2 failed attempts, when I reload the page and fail again, then the login is locked (the count survived the reload).
- **AC-21** (FR-28) Given the server returns `500` or is unreachable, when I click Login, then I see `Something went wrong. Please try again later.` and the Login button is enabled.
- **AC-22** (NFR-1, NFR-3, FR-29) Given the database is set up, when the stored row for `user@example.com` is read, then the password column does not contain `green apple house` and the value is a salted hash.
- **AC-23** (NFR-10, NFR-13, NFR-14, NFR-16) Given I use only the keyboard, when I Tab through the page, then focus goes email, password, show/hide, Login, each with a visible focus indicator, and every input has a linked label.

## 7. Assumptions

- **A-1** The "username field" is the email field; there is no separate username.
- **A-2** The password rule (3 words, 2 spaces) is checked at login as the story asks, even though such rules usually apply when a password is created. Account registration is out of scope.
- **A-3** "3 login attempts" means 3 consecutive failed attempts. The lock is per normalized email, not per browser or IP address.
- **A-4** After the lock ends, the user gets a fresh set of 3 attempts. The lock always lasts 5 seconds; it does not grow with repeated locks.
- **A-5** Format errors caught before sending are not "attempts".
- **A-6** Email is case-insensitive; password is case-sensitive and spaces matter.
- **A-7** The personal page only needs a welcome heading; its other content is out of scope.
- **A-8** The UI language is English.
- **A-9** The attempt counter and lock may live in memory in the back-end process (they reset when the server restarts); the accounts live in SQLite.
- **A-10** Logout, password reset, "remember me", and registration are out of scope.

## 8. Open questions for the product owner

- **Q-1** Should the lock apply per email (current assumption) or per device/browser? Per email means someone else can lock your account for 5 seconds by typing wrong passwords.
- **Q-2** Should the password field be cleared after a failed login (current assumption, FR-17), or kept so the user can preview it and fix a typo?
- **Q-3** Do you want a Logout button on the personal page?
- **Q-4** Should the UI be in English (current assumption) or Indonesian?
- **Q-5** Should repeated locks get longer (for example 5 s, then 30 s), or always stay 5 seconds (current assumption)?

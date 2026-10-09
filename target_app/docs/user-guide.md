# User guide: logging in

## Log in

1. Open the login page (for example <http://127.0.0.1:8000/>).
2. In **Email**, type your email address, for example `name@example.com`. Capital letters and spaces before or after the address don't matter.
3. In **Password**, type your password. Capital letters and every space do matter.
4. Click **Login**, or press Enter in either field.

If the email and password are correct, you go to your personal page, which shows `Welcome, <your email>`.

To try the app, use the demo account: `user@example.com` with the password `green apple house`.

You can do everything with the keyboard alone. Tab moves through Email, Password, Show, and Login, in that order.

## See the password you typed

Your password is hidden (masked) by default. Click **Show** next to the password field to see it as plain text. The button then reads **Hide**. Click **Hide** to mask the password again. Showing or hiding the password doesn't change it and doesn't log you in.

## Email rule

The email must look like a real address, for example `name@example.com`:

- one `@`, with a name before it and a domain after it
- a domain with at least one dot, ending in at least two letters (such as `.com` or `.co.id`)
- no spaces inside the address

## Password rule

The password must have **at least 3 words separated by spaces**, so it contains at least 2 spaces. For example:

| Password | Accepted? |
|---|---|
| `green apple house` | yes |
| `green apple house tree` | yes |
| `Gr33n! apple  house` | yes (two spaces in a row are fine) |
| `green apple` | no (only 2 words) |
| `greenapplehouse` | no (no spaces) |

Only the normal space bar counts as a space. Tabs don't. The password can be at most 128 characters.

## Messages

The page checks both fields before it sends anything. If something is wrong, a message appears under the field, and the cursor moves to the first field that needs fixing:

| Message | What to do |
|---|---|
| Please enter your email address. | Type your email. |
| Please enter a valid email address, for example name@example.com. | Check the email for typos. |
| Please enter your password. | Type your password. |
| Your password must have at least 3 words separated by spaces, for example: green apple house. | Check that your password has at least 3 words with spaces between them. |

When you change a field, its message goes away. These checks never count as failed attempts.

The following messages appear above the Login button:

| Message | Meaning |
|---|---|
| Email or password is incorrect. You have 2 attempts left. | The email and password don't match an account. The page keeps your email, clears the password, and puts the cursor in the password field. For security, it doesn't say which of the two was wrong. |
| Too many failed attempts. Please wait 5 seconds before trying again. | Login is locked. See the next section. |
| You can try logging in again. | The lock is over. |
| Something went wrong. Please try again later. | The server couldn't be reached or had a problem. This doesn't count as a failed attempt. |

## After three failed attempts

You get 3 attempts in a row:

1. 1st wrong attempt: `You have 2 attempts left.`
2. 2nd wrong attempt: `You have 1 attempt left.`
3. 3rd wrong attempt: login is **locked for 5 seconds**.

While login is locked:

- The page shows `Too many failed attempts. Please wait 5 seconds before trying again.`, and the number counts down every second.
- The Login button is disabled, and pressing Enter does nothing. You can still edit the fields.
- Even the correct password is refused until the lock ends, and reloading the page doesn't end it sooner.

When the countdown reaches 0, the page shows `You can try logging in again.` and the Login button works again. You then have 3 new attempts.

A successful login also resets the count to 3 attempts. Wrong attempts don't expire on their own. Only a lock ending or a successful login resets the count.

The count belongs to the email address, not to your browser. Wrong attempts for an address from any browser count toward its lock. Because the count is kept in the server's memory, restarting the server also resets it.

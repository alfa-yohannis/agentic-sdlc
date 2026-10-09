# User Story: Login Page

I am a normal user and I want to login to my account without confusing things, so I can see my personal page and use the website.

## What I need

- I want the username field to ask for my email address, because I dont want to remember another username.
- The system should check that the email looks like a real email, for example `name@example.com`.
- I want a password field where I can type my password safely.
- My password should have at least 3 words and contains at least 2 spaces between the words. For example: `green apple house`.
- There should be a button to preview the password, so I can check if I typed it right. When I click it again, the password should be hidden back.
- I want to click a Login button and get into my account when the email and password is correct.
- If I type something wrong, please show a simple error mesage that I can understand.
- I should only get 3 login attemps. After the third failed try, the login should be locked for 5 seconds before I can try again.
- The page should tell me when I need to wait, so I dont keep clicking the button and wonder why nothing is happening.

## Acceptance criteria

- The username input is required and accepts an email address.
- An invalid or empty email shows an error before login is completed.
- The password input is required.
- A password is valid only when it has at least 3 words and at least 2 spaces.
- The password is hidden by default, but the user can preview it with a show/hide control.
- A failed login increases the failed attemp count.
- The user can make no more than 3 failed login attemps.
- After 3 failed attemps, the login action is disabled for 5 seconds.
- After the 5 seconds is finished, the user can try logging in again.
- A successfull login resets the failed attemp count.

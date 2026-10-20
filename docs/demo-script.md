# Demo script (about 5 minutes)

Start the app (`docker compose up` or `python -m app`) and open http://127.0.0.1:8000. All people and numbers are fake.

## 1. The idea (30 seconds)

On the home screen, point at the three steps:

> "HR documents are full of SSNs, salaries and bank details. This assistant answers questions about them, but the AI model never sees any of it. Personal data is replaced with tags like `PERSON_5` first. Only HR can unseal the real values, and every reveal is logged."

## 2. An employee asks a policy question (1 minute)

Signed in as **Oliver** (employee), ask:

> How many days of paid sick leave do employees get?

Point out:
- the answer, **8 days**, and the source chip `DOC_n · p. 1` (the file name is sealed too: it often contains a name)
- the safety trail: Allowed · Masked · Searched · Answered · Safety check passed

## 3. The employee asks about a person (30 seconds)

Still as Oliver:

> What is Rebecca Heath's annual base salary?

> "Refused before anything is searched or sent to the AI. The question contained a name, so it never left this machine."

Optional: try `What is PERSON_5's salary?`. Typing a tag directly is refused too (an attack test found that hole).

## 4. HR asks the same question (1 minute)

Switch to **Charlotte** (HR). Note that the conversation clears:

> "So Charlotte's unsealed answers never stay on screen for the next person."

Ask:

> What is Rebecca Heath's annual base salary?

Point out:
- **Rebecca Heath** and **$111,500.00** are underlined as unsealed. Hover one to see its tag and that the reveal was logged
- the source is now the real file name, `personnel_file_heath.pdf · p. 2`
- open **What the AI saw**: `What is PERSON_5's annual base salary?`

> "The AI answered correctly without ever seeing her name or salary."

## 5. The audit log (30 seconds)

Open the **Audit log** tab: each value Charlotte unsealed, plus Oliver's refused question, with who, when and why. The questions themselves are never stored.

## 6. How you know it works (1 minute)

Show the Results table in the README and pick two points:

- **Measured, not assumed:** 381/381 private values found in the test documents, but only 68% on unseen documents. "That gap is why I tested on data the detector was never built from, with a held-out half scored once."
- **Attacked on purpose:** the attack tests found five real holes, all fixed. The most surprising: a search-library file held real values from leftover memory, fixed by writing the library from a separate process that never held real data.

Close with the limitations: demo sign-in, detection gaps (credit cards, passports), and that the strongest protection is architectural: the AI cannot leak what it never sees.

## Questions that work well

| Signed in as | Question | What happens |
|---|---|---|
| Oliver | How long is paid parental leave? | 12 weeks |
| Oliver | Will HR ever ask for my Social Security number by email? | No, never |
| Oliver | Who earns the most? | Refused |
| Charlotte | Who is Rebecca Heath's emergency contact? | Alexis Davis, unsealed |
| Charlotte | What is Nicole Day's phone number? | From the directory, unsealed |
| Either | What is the company's dress code? | "The documents do not say" (no guessing) |

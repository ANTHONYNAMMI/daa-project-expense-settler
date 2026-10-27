# DAA Project Expense Settler

## Project Overview

Expense Settler is a Python-based application developed as part of the Design and Analysis of Algorithms (DAA) project.

The application helps a group of people manage shared expenses and calculate how much each person owes or should receive.

## Problem Statement

When friends or groups share expenses, calculating each person's contribution and settling payments manually can be confusing.

This project aims to simplify expense sharing by calculating individual balances and identifying payments needed to settle the expenses.

## Objectives

- Record shared expenses.
- Calculate each person's total contribution.
- Determine individual balances.
- Identify who owes money to whom.
- Reduce manual calculations.

## Technologies Used

- Python
- HTML/CSS (if used in the project)
- JSON or other storage (depending on implementation)
- GitHub for source code management

## Key Features

- Add participants.
- Enter shared expenses.
- Calculate balances.
- Display settlement transactions.
- Save and retrieve expense data, if supported.

## Algorithm

The application calculates each participant's net balance using their contributions and share of expenses.

A positive balance means a participant should receive money.

A negative balance means a participant owes money.

A settlement algorithm can then match participants who should receive money with those who need to pay.

## How to Run

1. Install Python 3.10 or later.
2. Clone or download this repository.
3. Open the project folder in a terminal.
4. Follow the run instructions for the application's entry-point file.

Example:

```bash
python 04_expense_settler/app.py
```

If the project uses a shared module or requires running from a specific directory, follow the actual project structure.

## Testing

The application will be tested with different participant counts, expense amounts, equal and unequal expenses, and edge cases.

## Future Enhancements

- Expense history.
- Export settlement results.[data.json](https://github.com/user-attachments/files/33994946/data.json)
[app.py](https://github.com/user-attachments/files/33994934/app.py)
[common.py](https://github.com/user-attachments/files/33994928/common.py)

- Support for multiple groups.
- Improved user interface.

## Author

Student project developed for the Design and Analysis of Algorithms course.

## License

No open-source license has been specified.

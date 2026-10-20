"""Milestone 7: who may ask what, and who sees real values."""

import json
from pathlib import Path

import pytest

from src.roles import EMPLOYEE, HR, can_ask, can_see_real_values

ROSTER = json.loads((Path(__file__).resolve().parent.parent / "data" / "hr_roster.json").read_text())["employees"]

GENERAL = [
    "How many days of paid sick leave do employees get?",
    "How long is paid parental leave?",
    "Will HR ever ask for my Social Security number by email?",  # mentions SSN, but asks about a rule
    "How much PTO can I carry over?",
    "Does the company pay for health insurance?",
    "What are the public holidays?",
]

ABOUT_PEOPLE = [
    "What is Rebecca Heath's annual base salary?",  # a named employee (roster)
    "What is Nicole Day's phone number?",  # "Day" is also a word; the roster still knows her
    "Which bank account does employee EMP-1040 use?",  # an employee ID
    "Show me the SSN 282-32-3658 owner",  # an SSN
    "Who earns the most?",
    "What is the average salary of all staff?",
    "List everyone's home address",
    "What is John's salary?",  # a name the roster does not know
    "What is my manager's salary?",
]


@pytest.mark.parametrize("question", GENERAL)
def test_employee_may_ask_general_questions(question):
    assert can_ask(EMPLOYEE, question, ROSTER).allowed


@pytest.mark.parametrize("question", ABOUT_PEOPLE)
def test_employee_may_not_ask_about_people(question):
    decision = can_ask(EMPLOYEE, question, ROSTER)
    assert not decision.allowed and "limited to HR" in decision.reason


@pytest.mark.parametrize("question", GENERAL + ABOUT_PEOPLE)
def test_hr_may_ask_anything(question):
    assert can_ask(HR, question, ROSTER).allowed


@pytest.mark.parametrize("role", ["", "admin", "HR ", "contractor"])
def test_unknown_roles_are_denied(role):
    decision = can_ask(role, "What are the public holidays?", ROSTER)
    assert not decision.allowed and "Unknown role" in decision.reason


def test_refusal_says_why():
    reason = can_ask(EMPLOYEE, "Which bank account does employee EMP-1040 use?", ROSTER).reason
    assert "employee id" in reason


def test_only_hr_sees_real_values():
    assert can_see_real_values(HR)
    assert not can_see_real_values(EMPLOYEE)
    assert not can_see_real_values("admin")

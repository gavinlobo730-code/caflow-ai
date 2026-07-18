-- Migration 223: employee gender (for Maharashtra Professional Tax exemption)
--
-- Maharashtra State Tax on Professions, Trades, Callings and Employments Act,
-- 1975 (Sch. I), as amended w.e.f. 01-Apr-2023, fully exempts women earning up
-- to ₹25,000/month from Professional Tax. Computing MH PT correctly therefore
-- needs the employee's gender. Nullable free-text, normalized by the API to
-- 'male' / 'female' / 'other' (models/payroll.py::_normalize_gender). An unset
-- gender is treated as non-exempt by the PT engine — we never grant an
-- exemption we cannot substantiate.
ALTER TABLE payroll_employees ADD COLUMN IF NOT EXISTS gender text;

-- MySQL. Select benefit_demo as the default schema in Workbench first.
-- This is the raw input to the on-premises pseudonymization stage.
SELECT
    p.payment_id,
    p.household_id,
    c.citizen_id,
    c.name,
    c.age,
    c.gender,
    c.phone,
    c.address,
    p.pay_month,
    p.benefit_type,
    p.amount,
    r.household_size,
    r.recognized_income,
    t.income_limit
FROM benefit_payment AS p
INNER JOIN citizen AS c
    ON c.household_id = p.household_id
LEFT JOIN eligibility_review AS r
    ON r.household_id = p.household_id
    AND r.assessment_month = p.pay_month
LEFT JOIN eligibility_threshold AS t
    ON t.rule_year = CAST(SUBSTRING(p.pay_month, 1, 4) AS UNSIGNED)
    AND t.household_size = r.household_size
WHERE p.benefit_type = '생계급여(일반)'
ORDER BY p.payment_id;

# Flex Loan Manager Bot

> ⚠️ **Active Development Notice**: This tool is currently being built as an internal ops platform for managing Square Capital Flex Loans. If you're working on a similar manager bot for loans, please reach out to **@nadira** to avoid overlap and coordinate efforts.

## What Is This?

An internal tool for Square Capital ops/support teams to look up sellers by **Unit Token** and view their Flex Loan performance, repayment progress, GPV trends, and business health signals.

**Live Tool**: [https://nadira262.github.io/flex-loan-manager/](https://nadira262.github.io/flex-loan-manager/)

## Features

- 🔍 **Account Lookup** — Search by Unit Token to pull seller details
- 💰 **Active Loans** — View all active Capital loans (Flex, Term, MCA, etc.) with status, amounts, fees, hold rate, and risk grade
- 📈 **Repayment Progress** — Donut chart + repayment curve with projected payoff date
- 📊 **GPV Trends** — 180-day daily GPV with rolling average and anomaly detection (spikes/drops)
- ⚠️ **Business Health Signals** — Chargeback rate, dispute count, win rate, and alert flags
- 🔗 **Linked Accounts** — View other unit tokens tied to the same seller with active loans
- ✅ **Eligibility Checker** — 35 underwriting heuristics explaining why a seller is/isn't eligible for a loan

## Data Sources

| Table | Purpose |
|-------|---------|
| `APP_BI.HEXAGON.VDIM_USER` | Merchant/unit details, business name, MCC, location |
| `APP_CAPITAL.APP_CAPITAL.PLAN_GROUPS` | Loan details, risk grade, status, amounts |
| `APP_CAPITAL.APP_CAPITAL.PLAN_GROUP_DAILY_CUMULATIVE_REPAYMENT` | Repayment progress, outstanding balance, projected payoff |
| `APP_BI.HEXAGON_TABLE.AGGREGATE_SELLER_DAILY_PAYMENT_SUMMARY_BASE` | Daily GPV, payment counts, trends |
| `APP_RISK.APP_RISK.DISPUTES` | Chargebacks, dispute reasons, resolution status |

## Status

🚧 **Work in Progress** — Currently connecting to real Snowflake data. Mock data is used for demo purposes.

## Contact

**Owner**: Nadira Lachkar (@nadira)  
**Slack**: Reach out before starting any similar loan management tooling

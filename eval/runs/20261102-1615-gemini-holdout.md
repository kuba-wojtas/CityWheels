# Evaluation results

8 cases from `eval/holdout.toml`. A case passes in a run when all its checks
pass. Stable = passed in every run. Commit = the code the model ran on. 

| provider | model | runs | stable cases | passed runs | unsupported amounts | median time | avg tokens | commit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gemini | gemini-3.5-flash-lite | 3 | 5/8 | 19/24 | 1 | 1.7 s | 2694 | 0cad7cc |

## gemini / gemini-3.5-flash-lite (2026-11-02 16:15)

- PASS 3/3 `refund-exactly-48h-boundary`: Hi, if I cancel CW-1007 right now, do I still get the full rental price back or is it too late for that?
- FAIL 0/3 `voucher-booking-refund-to-card`: I paid for booking CW-1004 with a gift voucher. If I cancel it, can you send the money to my bank card instead?
  - missing amount 23 (3x)
- PASS 3/3 `pl-cancel-request-50pct`: Dzień dobry, proszę anulować moją rezerwację CW-1002. Ile wróci mi z ceny wypożyczenia?
- PASS 3/3 `booking-not-found`: Could you check my booking CW-1011? I forgot what time I'm supposed to pick up the bikes.
- PASS 3/3 `late-return-fee`: I'm out on bike CW-1008 now and I'm running late - I think I'll get it back to you around 13:30 today. How much extra will that cost?
- FAIL 2/3 `price-two-ebikes-three-hours`: How much would it be to rent two electric bikes for 3 hours, and how big is the deposit?
  - unsupported amounts 56 (1x)
- PASS 3/3 `deposit-in-cash`: I don't have a credit card. Can I just leave the deposit in cash when I pick up the bike?
- FAIL 2/3 `student-discount-not-covered`: Do you have a student discount? I have a valid student card.
  - didn't refuse (1x)

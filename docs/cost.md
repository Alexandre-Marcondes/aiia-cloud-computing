# Monetary cost analysis (Tasks 2.5, 3.6, 4.2, 4.3)

The assignment asks for **monetary cost** as one of the measured performance attributes in four
places: 2.5 (VM), 3.6 (serverless), 4.2 (VM vs N cameras), 4.3 (serverless vs N cameras). This note
records what the deployment actually cost, what it *would* cost at list price, and — honestly — what
we could not measure and why. It is a working note (see `docs/AGENTS.md`), not the graded report.

## TL;DR

- The **VM compute bills €0.00**. The meter literally reads **`B2ats v2 - Free`**: our
  `Standard_B2ats_v2` is covered by the **Azure for Students 750 h/month free grant**. The VM's only
  real charge is its **≈€1.59/month OS disk**.
- The **serverless pipeline is dominated by Azure AI Vision**: **€36.52 of €38.11** month-to-date.
- Because the actual VM figure is €0 (a student benefit, not a property of the architecture), every
  task is reported **two ways**:
  1. **Actual billed** — what this student subscription was charged (reproducible from Azure);
  2. **List price (PAYG)** — what the same usage costs at retail rates, so Parts 2/3/4 are
     comparable and the numbers mean something outside our free-tier account.

## Requirements (from `docs/Practice1.pdf`)

| Task | Required cost attribute |
| --- | --- |
| 2.5 | "detection efficiency, memory usage, CPU usage, bandwidth consumption, **monetary cost**, response time" |
| 3.6 | "detection efficiency, **monetary cost**, response time" |
| 4.2 | "memory usage, CPU usage, bandwidth consumption, **monetary cost**, response time" |
| 4.3 | "detection efficiency, **monetary cost**, response time" |

## How the numbers are read

- **`deploy/cost.sh`** (preferred, reproducible) — queries the Cost Management REST API
  (`Microsoft.CostManagement/query`, `ActualCost`, EUR) because `az consumption usage list` returns
  **null** on this student subscription. Default window: current month. Same numbers appear by hand
  in **Portal → Cost Management → Cost analysis**.
- **Meter-level query** — the same API grouped by `Meter` (used below to isolate the AI Vision line
  and to expose the `- Free` meters).
- **Retail Prices API** — public, no auth, used for the list prices.
- **Azure Monitor** — `TotalCalls` on the AI Vision resource (independent of the billing meter).

**Limitations of the cost data (they shape everything below).** Cost Management is **daily-granular**,
so a 60 s measurement window cannot be isolated — it is reported as the covering day. The **AI Vision
meter posts with a multi-day lag** (the Oct 17 line only appeared on Oct 18). Free-tier amounts and
grants are applied as separate **`- Free` meters at €0.00**, which *hide* the underlying usage from
the billed total.

## Actual billed cost (Cost Management, EUR, October 2026, month-to-date)

**VM resource group `<vm-resource-group>` (Parts 2.5, 4.2) — €1.5884 total**

| Meter | EUR |
| --- | --- |
| `E4 LRS Disk` (OS disk) | 1.1666 |
| `E4 LRS Disk Operations` | 0.4217 |
| `All Other Operations` + `Intra Continent Data Transfer Out` | 0.0001 |
| **`B2ats v2 - Free`** (the VM compute) | **0.0000** |
| **Total** | **1.5884** |

**Serverless resource group `<serverless-resource-group>` (Parts 3.6, 4.3) — €38.1084 total**

| Service | EUR | Main meter |
| --- | --- | --- |
| **Foundry Tools (AI Vision)** | **36.5171** | `Image Analysis Group 1 Transactions` |
| Storage | 1.5103 | LRS hot read/write/store + transactions |
| Event Grid | 0.0811 | `Standard Operations` |
| Functions (Flex) / App Service | 0.0000 | free grant (`- Free` meters) |
| **Total** | **38.1084** | |

**Subscription month-to-date: €41.5052** (the two RGs above ≈ €39.70, plus ≈ €1.81 of
`Virtual Network` — the VM's public IP — which sits outside these two groups).

**Day-of-measurement (Oct 17)** — the values the sweep/measurement reports cite:

| Window | VM RG | Serverless RG |
| --- | --- | --- |
| 2026-10-17 | €0.1004 (disk only) | **€7.8530** (AI Vision 7.5070, Storage 0.3190, Event Grid 0.0288) |
| 2026-10-18 (partial) | €0.0098 | €0.0019 |

The Oct 17 AI Vision line was **pending** in the original measurements (meter lag); it has now posted
and is the €7.5070 above. This closes the cost TODO previously tracked in `JOURNAL.md`.

**Azure Monitor cross-check.** AI Vision `TotalCalls`: **80 748** on 2026-10-11 (the N=256 sweep
day) and **18 691** on 2026-10-17, ≈0 elsewhere — ≈99 000 calls total. The billed Vision meter
(€36.52) is *lower* than `TotalCalls × unit price` would imply, because **throttled (HTTP 429) calls
are not billed** and part of the volume falls inside the free amount: the retry storm inflates
`TotalCalls` without inflating the bill proportionally.

## Unit prices (retail list, EUR)

| Resource | Price | Region |
| --- | --- | --- |
| `Standard_B2ats_v2`, Linux | **€0.0095 /hour** (≈ €0.228/day, ≈ €6.94/month always-on) | Belgium Central |
| `Standard_B2ats_v2`, Windows | €0.0176 /hour | Belgium Central |
| AI Vision **S1**, `Image Analysis Group 1` | **€0.88 /1000 transactions** (5 000/month free) | France Central |
| Hot LRS blob storage | read/write/store — from the billed meters, ≈€1.5/month at our volumes | — |
| Event Grid, Functions Flex, App Service | €0 at our volumes (free grants) | — |

Reproduce:

```sh
# VM hourly rate
curl -s "https://prices.azure.com/api/retail/prices?currencyCode='EUR'&\$filter=serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_B2ats_v2' and armRegionName eq 'belgiumcentral' and priceType eq 'Consumption'"
# AI Vision transaction rate
curl -s "https://prices.azure.com/api/retail/prices?currencyCode='EUR'&\$filter=contains(meterName,'Image Analysis Group 1 Transactions')"
```

## Per-task analysis

### Task 2.5 — VM, single stream
- **Actual billed:** €0.00 compute + ≈€0.03/day OS disk. The measurement window is invisible at
  daily granularity; the VM RG's whole month is €1.59.
- **List price:** compute is **flat €0.0095/h** regardless of load (burstable, but the base is metered
  per hour). Amortised over a 1 frame/5 s stream that is **≈ €0.013 per 1000 frames** — compute is
  *not* the cost driver.
- The real recurring lever is **egress**, not compute: the served annotated frame is ≈0.53 MB, so one
  viewer polling it every 0.5 s pulls **≈6 Mbps ≈ 64 GB/day**. Bandwidth billed €0.0001 in our
  window (free/negligible at our scale), but on a production SLS it would dominate.

### Task 3.6 — serverless
- **Actual billed:** the pipeline costs **€38.11/month-to-date**, of which **€36.52 is AI Vision**
  (≈96 %). Functions, App Service and Event Grid are €0–0.08. A healthy few-minute run is
  **€0** in practice (inside the 5 000 free transactions).
- **List price:** **€0.88 per 1000 frames** (Vision S1) — one Vision call per uploaded frame; storage
  and Functions are rounding errors. A healthy T3 run of **362 frames** = **€0.32** at list price.
- Retries multiply cost: at overflow the same frame is billed more than once because the 429 retry +
  Event Grid redelivery re-call Vision (`TotalCalls` 2× the frame count at N=192).

### Task 4.2 — VM vs N cameras
- **Actual billed:** €0.00 compute, unchanged from 2.5 — the cost is **flat** in N.
- **List price:** still **€6.94/month** for any N the box can serve. Compute is *not* the limit — the
  box is **memory-bound** and saturates at ≈**6 cameras** (see `docs/measurements/`). Egress grows
  with the number of served frames, but compute cost does not.
- **Takeaway:** on a paid account the VM gives "up to ~6 cameras for a fixed €7/month".

### Task 4.3 — serverless vs N cameras
- **Actual billed:** €38.11 MTD, Vision-dominated; the number scales with frames processed, not with
  wall-clock.
- **List price** at 1 frame/5 s per camera, **€0.88/1000 frames** → **€0.6336 × N per hour**
  (€15.21 × N per day), *before* the 5 000 free transactions:

| N | offered rate | list price /hour | list price /day |
| --- | --- | --- | --- |
| 6 (the VM's knee) | 1.2 fps | €3.80 | €91.2 |
| 64 | 12.8 fps | €40.6 | €973 |
| 128 | 25.6 fps | €81.1 | €1 946 |
| 144 (ceiling edge) | 28.8 fps | €91.2 | €2 190 |
| 192 (overflow) | 38.4 fps | €121.7 | €2 920 |

**Takeaway:** serverless **scales linearly and expensively** — it keeps up to ≈144 cameras, but at
list price the Vision bill grows without bound, whereas the VM's cost is flat (and it stops at ~6).

## The comparison that matters

| Platform | Actual billed (student) | List price | Cameras served |
| --- | --- | --- | --- |
| Part 2 VM | €0.00 compute + €1.59/mo disk | **€6.94/month, flat** | ≈6 (memory-bound) |
| Part 3 serverless | €38.11/mo (96 % Vision) | **€0.88 per 1000 frames** (linear) | ≈144 (Vision-bound) |

Per frame, list price: VM ≈ **€0.013/1000 frames** (amortized) vs serverless ≈ **€0.88/1000 frames**
— serverless Vision is ≈**67×** the VM's amortized compute per frame. The serverless advantage is not
cost but **headroom** (~144 vs ~6 cameras) and zero idle cost; the VM's advantage is a **flat, tiny**
bill that does not grow with load.

## Why the VM shows €0 (and it is not a bug)

The VM is a `Standard_B2ats_v2`, one of the three sizes **Azure for Students includes 750 h/month free
for 12 months** (with `B1s` and `B2pts_v2`). One always-on instance ≈730 h/month fits inside the
grant, so the compute meter is the `B2ats v2 - Free` line at €0.00. **Student credit ($100) and the
free monthly amounts are separate benefits** — the grant zero-rates the meter; it is not a credit
being drawn down. Caveats worth stating in the report: the grant is **12-month only**, applies to
**exactly those SKUs in supported regions**, is **750 h/month per size** (not per VM), and **the disk
and public IP still bill** (the €1.59 + €1.81 above).

## What we could not measure — and why

1. **A non-zero actual VM compute cost.** The student grant zero-rates it. We report the **list
   price** instead and state the grant explicitly. *Why:* it is a benefit of the account, not of the
   architecture.
2. **Per-window (60 s) cost.** Cost Management is daily-granular; a sweep's cost is only visible as
   part of the covering day. *Why:* the API's minimum billing granularity is one day.
3. **Several AI Vision lines at first read.** The Vision meter lags several days; the Oct 17 line is
   now captured (€7.5070), but a re-run is still needed to finalize any window measured within the
   last 2–3 days. *Why:* delayed meter posting.
4. **Production-representative totals.** Our usage is short bursts (sweeps of 60 s), not a 24/7 SLS;
   the €38.11 month is dominated by a handful of throttling sweeps and their retries. Real running
   cost must be extrapolated from the list prices above. *Why:* the measurements are deliberately
   time-boxed.
5. **Egress cost at scale.** Bandwidth billed ≈€0.0001 here; the 64 GB/day-per-viewer figure is a
   projection, not a billed amount. *Why:* our windows are minutes long.
6. **The consumer-facing report itself.** The graded report is not in this repo (`docs/report/` was
   removed during de-identification); this note supplies the numbers/tables to place there. The
   concrete resource-group names and host live in `.env`.

## Reproduction (one command each)

```sh
# Actual billed, per day + per service, this month (both RGs)
bash deploy/cost.sh
# The Oct-17 measurement-day window
bash deploy/cost.sh --from 2026-10-17 --to 2026-10-18
# A single group
bash deploy/cost.sh --rg <serverless-resource-group>
```

Meter-level breakdown (used to isolate AI Vision and expose the `- Free` meters) is the same REST
call grouped by `Meter` (see `docs/performance.md` "Monetary cost" for the surrounding protocol).

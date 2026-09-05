# Blocking external approvals

Two third-party approvals sit on botly's critical path. Neither is engineering work,
both take weeks, and both were meant to be filed on the same day as build-order step 1.
**As of 2026-09-05 neither has been started.** Code is now two build-order steps ahead
of the paperwork.

Update the status lines below as things move. This file exists so the wait is visible
rather than remembered.

---

## 1. Shopee Open Platform — partner registration

| | |
|---|---|
| **Status** | ⬜ Not started (as of 2026-09-05) |
| **Submitted** | — |
| **Decision** | — |
| **Gates** | Build-order step 5 (Shopee data client and commerce tools) |
| **Portal** | Shopee Open Platform (`open.shopee.com`) — verify the correct regional portal for the target market before registering |

**Why it is the higher risk of the two.** For this audience Shopee is simultaneously a
channel *and* the order database. A WhatsApp-only bot still needs Shopee access to answer
"where is my parcel" — which is the question the product exists to answer. Registration is
gated and region-scoped, and approval is not guaranteed.

**Known unknowns to resolve during application:**
- Which regional portal applies, and whether a local business entity is required
- Whether seller chat APIs and order/logistics read APIs need separate approvals
- Sandbox availability before production credentials

**If refused:** step 5 needs replanning. Mitigation already in the architecture — commerce
tools sit behind a Protocol, so a manual CSV order import can substitute temporarily.

---

## 2. WhatsApp Business — Cloud API + business verification

| | |
|---|---|
| **Status** | ⬜ Not started (as of 2026-09-05) |
| **Submitted** | — |
| **Decision** | — |
| **Gates** | Build-order step 6 (WhatsApp adapter, templates and window handling) |
| **Portal** | Meta Business Manager → business verification, then WhatsApp Cloud API setup |

**What the application actually involves** (verify current requirements at time of filing):
- A Meta Business Manager account with business verification (legal entity documents)
- A phone number not already registered to a WhatsApp account
- Display-name review for the sender
- Message templates submitted individually for approval — these are needed *before* the
  dispatcher can send anything outside the 24-hour service window

**If refused:** the primary v1 channel is lost. Telegram carries the demo meanwhile, and a
BSP (Twilio, 360dialog) is the fallback route — slower and more expensive, but it bypasses
direct verification.

**Separate live risk:** per-conversation billing. Model the cost before pricing. If the
unit economics do not clear seller willingness to pay, the channel is commercially wrong
even when technically approved.

---

## Why Telegram is unaffected

Build-order step 3 is Telegram precisely because it has no gatekeeper — a BotFather token
and a webhook. It proves the entire ingress → queue → runtime → dispatcher pipeline end to
end while these two approvals are in flight. That sequencing is deliberate and still holds.

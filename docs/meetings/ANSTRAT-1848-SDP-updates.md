# ANSTRAT-1848 SDP updates (for handbook PR #1223)

**Purpose:** Copy-paste or merge this content into the System Design Proposal in [ansible/handbook PR #1223](https://github.com/ansible/handbook/pull/1223) so the SDP reflects the latest decisions and blockers from the saas-stage-routing work.

**Source:** `~/src/saas-stage-routing/` (summary.md, entries 2026-03-03 and 2026-03-06).  
**Refinement alignment:** [ANSTRAT-1848-refinement-plan.md](ANSTRAT-1848-refinement-plan.md).

---

## 1. Chosen architecture (replace or supersede Transit Gateway + squid)

**Selected solution: Option C — PrivateLink + NAT Gateway + Akamai whitelisting**

- Spoke accounts connect to hub via PrivateLink with private DNS (no Route 53 split DNS).
- Hub VPC: NLB → reverse proxy → NAT Gateway with **static EIPs** → Akamai.
- No Transit Gateway, no VPN, no squid proxy. 3scale is public-facing via Akamai; only egress IP whitelisting is required.

**Traffic flow:**
```
Spoke app → PrivateLink (private DNS) → NLB → Reverse Proxy → NAT GW (EIP) → Akamai → 3scale → insights-ingress-go
```

**Target endpoint:** `https://cloud.stage.redhat.com/api/ingress/v1/upload`

---

## 2. Static egress IPs and current blocker

**Static egress IPs (received 2026-03-03):**
- `54.146.227.199`
- `52.0.219.139`
- `35.174.84.177`

**Blocker — Akamai preprod lockdown whitelist:**

- Akamai’s pre-production lockdown rule for `cloud.stage.redhat.com` must allow traffic from these three IPs.
- **NetBox** is on-prem only and does not hold AWS egress IPs; IT Network (UR0101073) directed to other paths.
- **Paths for whitelisting:**
  1. **InfoSec exception:** Incident INC4595478 routed to InfoSec for approval; after approval, xding (Network) will add the 3 egress IPs to bypass the lockdown rule.
  2. **MP+ public egress IP spreadsheet:** Alternative path for AWS egress IPs (Akamai team to advise).
- **CDN request:** [DAT-10614](https://issues.redhat.com/browse/DAT-10614) — update with these IPs and current status (InfoSec/MP+).

**Status (as of 2026-03-06):** InfoSec exception review in progress (INC4595478). No internal path to `cloud.stage.redhat.com` exists today; split DNS / internal path is out of scope for this initiative.

---

## 3. Security (external IPs and Thomas Eagle review)

- **External IPs:** The solution uses three **public** egress IPs from the hub NAT Gateway; these must be whitelisted in Akamai’s preprod lockdown (see above). Same restrictions as normal inbound interface apply; pre-prod to pre-prod is acceptable per ESS rules (no prod data to preprod).
- **Product security:** Consult Thomas Eagle (product security architect, Ansible) once the design is final, especially regarding external IPs and network changes. Align any Jira task comments (e.g. AAP-66644) with this SDP wording.

---

## 4. Phase 1 verification (test plan)

- **Phase 1** = establish connectivity and confirm that staging **receives** data (e.g. billing/analytics payloads to `cloud.stage.redhat.com/api/ingress/v1/upload`). Validation via Prometheus/Grafana and non-firing alerts is in scope.
- **“Receive”** should be qualified in the proposal (e.g. billing code vs subscription watch (swatch) as needed).
- **Phase 2** (end-to-end data validation / data accuracy) is out of scope for this initiative.

---

## 5. Blocking problem statements (for Architecture task)

- **Akamai preprod whitelist:** Pending InfoSec exception (INC4595478) and/or MP+ spreadsheet; CDN request DAT-10614. Once whitelist is in place, connectivity from hub egress to stage can be validated.
- **Hub implementation:** Forward proxy + NAT GW with static EIPs (Option C) — in progress; static IPs provided by Razique (2026-03-03).

---

## 6. Docs / SAS ownership

- Internal docs (hub–spoke, private link, SAS-owned infrastructure) are owned by the SAS team; analytics team does not own this architecture. Handbook/docs in the PR should reflect that where relevant.

---

*After merging these updates into the SDP, re-check refinement alignment (Architecture AAP-66641, Test plan AAP-66645, Security AAP-66644, CI/CD AAP-66646, Docs AAP-66642) and adjust Jira task comments if needed.*

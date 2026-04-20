# robotrocketscience LLC -- Formation Draft

**Status:** DRAFT for CPA review
**State:** California
**Date:** 2026-04-19

---

## 1. Business Purpose Statement

(For Articles of Organization, Item 3 -- California allows "any lawful purpose" but a specific statement is useful for the operating agreement and banking.)

> Research and development engineering services, including but not limited to: first-principles analysis, computational simulation and modeling, software development, and the design, testing, and publication of open-source and proprietary software products.

## 2. Formation Checklist

| Step | Document/Action | Fee | Notes |
|------|----------------|-----|-------|
| 1 | Articles of Organization (Form LLC-1) | $70 | File via [BizFile Online](https://bizfileonline.sos.ca.gov/) |
| 2 | Statement of Information (Form LLC-12) | $20 | Due within 90 calendar days of formation |
| 3 | EIN (IRS Form SS-4) | Free | [Apply online at IRS.gov](https://www.irs.gov/businesses/small-businesses-self-employed/apply-for-an-employer-identification-number-ein-online) |
| 4 | Operating Agreement | N/A | Not filed with state, but required by CA law to have one |
| 5 | CA Franchise Tax Board | $800/yr | Annual minimum franchise tax (due by 15th day of 4th month) |
| 6 | Business bank account | Varies | Needed to maintain liability shield (no commingling) |

## 3. Articles of Organization -- Key Fields

- **LLC Name:** robotrocketscience LLC
- **Business Address:** [home address or registered agent]
- **Agent for Service of Process:** [CPA father or registered agent service]
- **Management:** Member-managed (single-member LLC)
- **Purpose:** Any lawful act or activity (standard CA default)
- **Organizer:** [your legal name]

## 4. Operating Agreement -- Key Provisions

Even for a single-member LLC, California requires an operating agreement. It does not need to be filed with the state. Key sections:

### 4.1 Company Purpose

Research and development engineering, first-principles analysis, simulation and modeling services, and the development, publication, and licensing of software products. Specific activities include:

- **Open-source software development and publication.** Development and MIT-licensed release of software tools including but not limited to agentmemory (persistent memory system for AI agents), ascii-render-machine (image-to-ASCII renderer), solar-system-wallpaper (ephemeris wallpaper generator), and related projects published at github.com/robot-rocket-science.

- **Quantitative analysis and simulation.** Design, backtesting, and operation of quantitative strategies for financial markets, including options analysis, statistical arbitrage research, and related computational modeling.

- **Infrastructure and cloud services.** Operation of development infrastructure including self-hosted servers, Cloudflare workers, and cloud compute for R&D purposes.

- **Consulting and contract engineering.** Provision of engineering analysis, simulation, modeling, and software development services to third parties.

### 4.2 Intellectual Property

All software, research, documentation, and related IP created under the LLC's operations is owned by the LLC. Open-source releases under MIT license are authorized by the sole member. The member retains the right to contribute to and publish open-source software.

### 4.3 Initial Capital and Assets

Assets transferred to the LLC upon formation:

| Asset | Description |
|-------|-------------|
| agentmemory | Persistent memory system for AI agents. 28 modules, 872 tests, 26 MCP tools. Published under MIT license. |
| alpha-seek | Quantitative options strategy research platform. Backtesting infrastructure on GCP. |
| optimus-prime | Options strategy research codebase. 61 files, ~15.6K LOC. DuckDB/GCP compute. |
| ascii-render-machine | ASCII art rendering engine. Published under MIT license. |
| solar-system-wallpaper | JPL Horizons ephemeris wallpaper generator. Published under MIT license. |
| robotrocketscience.com | Portfolio website and domain name. Cloudflare hosted. |
| email-secretary | Gmail triage automation. Claude API integration. |
| sports-betting-arbitrage | Odds aggregation and EV detection research platform. |
| bigtime | LAN compute mesh daemon. Cross-platform. |
| gsd-2 | AI agent orchestration framework. npm package. |
| Infrastructure | Gitea server, Cloudflare workers, GCP compute, home server fleet (debserver). |

### 4.4 Financial Activity Categories

For CPA tax planning:

1. **Software licensing revenue** -- potential future revenue from software products or SaaS wrappers
2. **Consulting/contract engineering** -- simulation, modeling, analysis services
3. **Trading activity** -- options strategies (alpha-seek, optimus-prime) if/when live
4. **API/compute costs** -- Anthropic API, GCP, Cloudflare, Odds API, JPL Horizons (deductible R&D expenses)
5. **Hardware** -- development machines, home server fleet, sensors/hardware for R&D

### 4.5 Liability Considerations

The LLC structure specifically addresses:

- **Published software liability.** MIT license disclaims warranty, but the LLC provides an additional liability barrier between published software and personal assets.
- **Financial trading.** Options strategies and sports betting algorithms carry inherent financial risk. LLC separates trading losses and potential regulatory exposure from personal assets.
- **Data processing.** agentmemory and email-secretary process user data (belief stores, email content). LLC limits personal exposure from data handling incidents.
- **Cloud infrastructure.** Operating Cloudflare workers and GCP compute creates service provider liability best held by an entity.

## 5. Ongoing Compliance

| Requirement | Frequency | Cost |
|-------------|-----------|------|
| CA Franchise Tax | Annual | $800 minimum |
| Statement of Information (LLC-12) | Every 2 years | $20 |
| Federal tax return (Form 1040, Schedule C or 1065) | Annual | CPA fees |
| CA tax return (Form 568) | Annual | CPA fees |
| Business bank account reconciliation | Monthly | -- |

## 6. Cost Summary (Year 1)

| Item | Cost |
|------|------|
| Articles of Organization | $70 |
| Statement of Information | $20 |
| EIN | Free |
| CA Franchise Tax | $800 |
| Registered agent (if not self/CPA) | $0-$150/yr |
| **Total (minimum)** | **$890** |

## 7. Notes for CPA

- Single-member LLC, member-managed
- Primary activity is R&D with no current revenue -- the $800 annual franchise tax applies regardless
- Multiple project categories (software, trading, consulting) may benefit from tracking as separate cost centers within the LLC rather than separate entities
- S-corp election (Form 2553) not recommended until revenue exceeds ~$40-50K to justify reasonable salary requirement
- R&D tax credit (federal Form 6765, CA form FTB 3523) may apply to software development and quantitative research activities -- worth evaluating
- Trading activity (if/when live) may warrant mark-to-market election (Section 475(f)) depending on volume

---

*This is a draft for discussion with a CPA/attorney. It is not legal or tax advice.*

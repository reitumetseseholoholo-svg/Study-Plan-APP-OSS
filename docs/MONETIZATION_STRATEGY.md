# Monetization strategy: free OSS + paid Pro

This document sketches a path to revenue while keeping the core app open-source and community-friendly. It is a planning reference, not a commitment to any particular product or pricing.

---

## 1. Principle: OSS as lead magnet, paid layer for revenue

- **Open-source (current repo):** Full-featured study coach: Pomodoro, SRS quizzes, local AI tutor (Ollama), syllabus import, coach pick, daily plan. Stays free and auditable; builds trust and adoption.
- **Paid layer:** Optional products or services on top that people pay for. Revenue comes from here, not from locking the app itself.

---

## 2. Free (OSS) vs paid (Pro / commercial) — draft split

| Area | Free (OSS) | Paid / Pro (sketch) |
|------|------------|----------------------|
| **Core app** | Full desktop app, all current features | Same binary; no artificial limits in OSS build |
| **AI tutor** | Local only (Ollama); user runs models | Optional: hosted AI tier (API quota, better models, no local setup); or “Pro” prompts/templates |
| **Sync / multi-device** | Local data only (`~/.config/studyplan`) | Optional: cloud sync, backup, “restore on new machine” |
| **Modules / content** | User adds own modules, syllabus, questions | Optional: curated/verified module packs, official syllabus mappings, question banks (where licensable) |
| **Support** | Community (issues, discussions) | Optional: priority support, onboarding, or consulting |
| **Institutions** | Single user, self-hosted | Optional: site license, SSO, usage reporting, managed deployment |

The idea: the app stays fully usable for free. Pro/commercial options are **add-ons** (hosted AI, sync, content, support, B2B), not “crippled free vs full paid.”

---

## 3. Revenue channels (in order of “max money” potential)

1. **B2B / institutions**  
   Tuition providers, employers, training departments. Sell: site license, managed install, support, reporting. Highest revenue per customer.

2. **Hosted / cloud upsell**  
   Optional cloud AI (no Ollama required), optional sync/backup. Recurring (subscription) revenue.

3. **Content / add-ons**  
   Curated module packs, question banks, or premium templates (where license allows). One-time or subscription.

4. **Donations / sponsor**  
   GitHub Sponsors, Open Collective, “buy me a coffee.” Good for goodwill and some income; usually smaller than B2B or subscriptions.

5. **App stores**  
   Package the same OSS app for store distribution (e.g. Flathub, Snap, or a paid “Pro” build with hosted features). Can increase reach; store cut and policies apply.

---

## 4. What to keep in the repo (and docs)

- **Code:** Keep the main app fully functional and open. No intentional crippling of the OSS build.
- **Docs:** This file and `DEVELOPER_DOC.md` describe the **strategy** (free vs paid, where revenue could come from). No need to promise specific products or dates.
- **Community:** Reddit, issues, and discussions stay focused on the free app; paid offerings can be mentioned as “optional” when relevant (e.g. “for hosted AI / sync, see [link]”).

---

## 5. Summary

- **Best for “most money”:** Treat OSS as the free, trusted core. Add a **paid layer**: institutional licenses, hosted AI/sync, premium content, or support. Promote the app (e.g. Reddit, SEO) to grow users; convert a fraction to paid where value is clear.
- **Best for “most impact” first:** Stay fully OSS and community-focused; add donations or a small “Pro” tier later without breaking the free experience.

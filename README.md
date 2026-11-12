# Measuring how Taiwanese news media portray the KMT and the DPP, 2012–2026

**An open, reproducible study · code, method and early results · [website](https://chih-kai-wang.github.io/tw-media-lean/)**

[English](#english) · [繁體中文](#繁體中文)

> **Status, 12 November 2026.** These are early results. Observation of the 28 November 2026 local elections continues until 28 December, and the election-period numbers may change after the decision model is recalibrated (§8). The scores describe how news reports present each party.

---

<a id="english"></a>

## Abstract

This project measures how 12 Taiwanese news outlets present the Kuomintang (KMT) and the Democratic Progressive Party (DPP), month by month from 2012 to 2026, with uncertainty intervals, using only public data and methods anyone can rerun.

A large language model (LLM), Gemini 3.8 Flash, reads about 14,000 articles without seeing the outlet's name and scores each party from −2 (very negative) to +2 (very positive). A small Chinese text model is then trained to imitate those scores, and it scores the remaining articles: 269,609 so far, of which 190,144 are political. A random-walk model smooths each outlet's monthly averages.

The labels are checked in several ways. Each party's own press releases should read as positive for that party, and they do: 90% of KMT releases and 94% of DPP releases. Swapping the party names in an article should swap the scores; the leftover effect is 0.07 points on a 4-point scale. Three other models from different companies rank the outlets almost the same way (rank correlation 0.96–0.99).

The outlets spread from FTV News (DPP more favourable by 1.36 points in 2024–26) to China Times and The Storm Media (KMT more favourable by 0.64).

## Contents

1. [Introduction](#1-introduction)
2. [Background](#2-background)
3. [Data](#3-data)
4. [Labelling with a language model](#4-labelling-with-a-language-model)
5. [The decision model](#5-the-decision-model)
6. [Checking the labels](#6-checking-the-labels)
7. [Trends over time](#7-trends-over-time)
8. [Watching the 2026 election](#8-watching-the-2026-election)
9. [What did not work](#9-what-did-not-work)
10. [Results](#10-results)
   - [10.1 Other patterns](#101-other-patterns)
11. [Not done yet](#11-not-done-yet)
- [Appendix A. Reproducing the results](#appendix-a-reproducing-the-results)
- [Appendix B. Where each part lives in the code](#appendix-b-where-each-part-lives-in-the-code)
- [Appendix C. How the project was run](#appendix-c-how-the-project-was-run)
- [Licence and data use](#licence-and-data-use)
- [References](#references)

---

## 1. Introduction

### 1.1 The question

Taiwanese readers often describe outlets as "blue" (closer to the KMT) or "green" (closer to the DPP), but these labels are rarely measured. This project asks a narrower question that can be measured:

> In articles that mention a party, how positively or negatively is that party presented, and how has this changed since 2012?

The two parties are scored separately, each on its own scale. An outlet can be harsh on both, or kind to both. The third party, the Taiwan People's Party (TPP), is labelled too, but its scores are not yet reliable enough to publish (§5.3).

### 1.2 Why it is hard

1. **There is no answer key.** Nobody has scored hundreds of thousands of Taiwanese articles for how they present each party.
2. **Scale.** Twelve outlets over fifteen years is far too much text to read, or even to send to a large model at a reasonable cost.
3. **Incomplete archives.** Outlets keep their old articles for different lengths of time, and the Internet Archive holds only part of the rest, so some outlets start later than 2012 (Table 3.1).
4. **Who governs matters.** The party in government is the subject of most policy news and receives most criticism. The KMT governed until May 2016, the DPP since then, so part of any change across 2016 reflects the change of government.

### 1.3 Our approach

```
     news websites, 2012–2026                 party press releases
  (monthly random sample + live feed)          (known stance: anchors)
                 │                                       │
                 ▼                                       │
   an LLM labels ~14,000 articles  ◄─────────────────────┘
   (outlet name hidden, fixed codebook)
                 │                      checks: anchors, party-swap test,
                 │                      three other LLMs, a reworded prompt,
                 ▼                      a word-based method that uses no LLM
   a small Chinese model learns to imitate the LLM
                 │
                 ▼
   it scores every sampled article (269,609)
                 │
                 ▼
   a random-walk model smooths each outlet × party × month,
   with 95% intervals and known events (change of government, owner)
                 │
                 ▼
   website, data files, report
```

---

## 2. Background

**Stance.** For each article and each party it mentions, the label is an integer from −2 (strongly negative) to +2 (strongly positive), with 0 for neutral or balanced. The rules are in [docs/codebook.md](docs/codebook.md). The key rule is that the label describes how the article presents the party: a scandal reported plainly, with the party's response, is −1; the same scandal told in loaded words and from one side only is −2.

**Outlet score.** An outlet's score for a party in a period is the mean stance over its articles that mention the party. The summary used below is the KMT score minus the DPP score: positive means the KMT is presented more favourably than the DPP.

**Language model as labeller.** A large language model can follow a written codebook and label text at a fraction of the cost of human labellers (Gilardi et al., 2023). It can also carry its own biases, which is why §6 exists.

**Distillation.** Sending every article to a large model costs money each time. Instead, a small model (BERT, about 100 million parameters) is trained on the large model's labels. Running it afterwards is free, and the same model gives the same answer every time.

**Calibration.** A model trained this way tends to pull its scores toward the middle. Calibration fits a straight line that maps the small model's scores back onto the large model's scale (§5.2).

---

## 3. Data

### 3.1 Outlets

| Outlet | 中文 | Earliest data | Where the history comes from |
|---|---|---|---|
| Central News Agency (CNA) | 中央社 | 2012 | own site; Internet Archive before 2014-07 |
| Liberty Times | 自由時報 | 2012 | own site |
| United Daily News | 聯合報 | 2015 | Internet Archive (its robots.txt excludes the pre-2015 paths) |
| China Times | 中國時報 | 2012 | own site |
| ETtoday | ETtoday | 2012 | own site |
| TVBS | TVBS | 2013 | own site |
| SET News | 三立 | 2013-10 | own site |
| FTV News | 民視 | 2012 | Internet Archive to 2017; own site from 2019; no 2018 |
| EBC News | 東森 | 2018-03 | own site |
| Public Television Service (PTS) | 公視 | 2012 | own site |
| The Storm Media | 風傳媒 | 2014 | own site |
| Mirror Media | 鏡週刊 | 2016-11 | Internet Archive |
| CTi News (added 12 Nov 2026) | 中天 | 2026-01 | own site's monthly sitemaps; no politics section, so political articles are drawn from its main-news section (要聞); earlier years on the Internet Archive are being checked |

**Table 3.1.** The outlets. CTi News was added on 12 November 2026 and has data from January 2026 only, so it is on the website and in §10 but not in Table 10.1; its cable channel lost its licence in December 2020, and its news site keeps lists of articles only from January 2026. Details in [docs/collection-status.md](docs/collection-status.md) and [docs/archive-url-schemes.md](docs/archive-url-schemes.md).

### 3.2 Two ways of collecting

- **Historical sample (to September 2026).** For each outlet and month, up to 300 politics articles are drawn at random. The sampler takes turns across months, so an interrupted run still covers every month evenly.
- **Live collection (from 31 October 2026).** Every hour, the newest articles are read from each outlet's sitemap, in every section.

The switch between the two changes what is collected, and §8.2 shows what that does to the trends.

Social platforms (YouTube, PTT, LINE TODAY) are also collected, but they are not part of the results yet.

### 3.3 Collection rules

- An honest User-Agent, robots.txt obeyed, at most one request per second per site.
- No logging in, and no getting around blocks or bot checks. A source that blocks us is dropped.
- Sources whose robots.txt says `ai-train=no` (PTT, CNA) are labelled and scored, but never used to train a model.
- Article text is not republished. Only URLs, titles, labels and aggregates are. User names on discussion platforms are hashed ([docs/privacy.md](docs/privacy.md)).

---

## 4. Labelling with a language model

Each article is sent to the model with a fixed codebook ([docs/codebook.md](docs/codebook.md)), without the outlet's name. The model returns JSON with:

- whether the article is about Taiwanese politics;
- its genre and main topic;
- for each of the three parties: whether it is mentioned, how prominent it is (0–3), whether its people are quoted, and its stance (−2 to +2).

**Why a language model.** The author did not label articles by hand, for two reasons: the author's own labels could carry personal political leanings, which is what the study measures, and one person cannot label tens of thousands of articles. Language models from several different companies and model families were used instead, so that they can be checked against each other.

The main labeller (the "teacher") is **Gemini 3.8 Flash**, run as Google Cloud Vertex AI batch jobs. It labelled 13,920 news articles and press releases for training, balanced across outlets and periods. It also labels a sample of live articles every week (§8.1).

Three more models labelled the same 2,836 articles as a check (§6.3): Gemini 3.5 Flash-Lite (Google), gpt-oss-120b (OpenAI, open weights) and Llama 4 Maverick (Meta, open weights). The plan allowed at most one model from a Chinese company; none was available on Vertex AI at the time, so none is included.

---

## 5. The decision model

### 5.1 Architecture

The decision model is `ckiplab/bert-base-chinese` with one small classifier ("head") per codebook question, reading the first 512 characters of each article. It was trained for 3 epochs on 11,106 articles, with 1,342 for validation and 1,472 held out for testing. The split is by article.

Training samples are weighted by 1/√(articles in that outlet × period), so large outlets do not dominate. The stance classes are weighted too. Each head's probabilities are temperature-calibrated on the validation set.

### 5.2 Calibrating the stance scale

The model outputs a probability for each of the five stance values. Its raw score $x$ is the expected value:

```math
x = \sum_{k=-2}^{2} k \, p_k \qquad (5.1)
```

On the validation set, for each party, we fit the raw score against the teacher's label $t$, then invert the line:

```math
x = c + d\,t \quad\Rightarrow\quad \text{calibrated} = \frac{x - c}{d} \qquad (5.2)
```

Fitting this way round gives calibrated scores whose average matches the teacher's in every group, which is what outlet averages need. The opposite fit, predicting $t$ from $x$, minimises the error on each article but pulls every average toward the middle (§9).

### 5.3 Test results

The pass criteria were written down before training: for both parties, mean shift smaller than 0.03 and slope greater than 0.8.

| Party | Articles | Shift (model − teacher) | Slope | Mean absolute difference | Used |
|---|---:|---:|---:|---:|---|
| KMT | 886 | −0.008 | 0.96 | 0.44 | yes |
| DPP | 1,028 | −0.019 | 0.93 | 0.41 | yes |
| TPP | 183 | −0.034 | 1.17 | 0.66 | **no** |

**Table 5.1.** Decision model v1 against the teacher on the held-out test set ([docs/decision-model.md](docs/decision-model.md)).

TPP is not used: with only 183 test articles, the calibration had to stretch the scale almost three-fold, and errors on individual articles became large.

On outlet × period cells with at least 30 articles per party (38 cells), the model's KMT − DPP agrees with the teacher's with rank correlation 0.96, mean absolute difference 0.15 and overall shift −0.01. Scores for single articles are noisier than the teacher's; the model is meant for averages over hundreds of articles.

---

## 6. Checking the labels

The labels are checked against things that anyone can rerun.

### 6.1 Known-stance anchors

A party's own press releases should present that party positively. Over 2012–2026, the teacher scored the party itself as positive in 893 of 996 KMT releases (90%) and 924 of 988 DPP releases (94%), in years of both governments ([docs/bulk-annotation.md](docs/bulk-annotation.md)). Press releases are clearer than news, so this is an upper bound on accuracy.

### 6.2 Party-swap test

Politicians' names are replaced by placeholders that keep the party (for example "KMT person A"), using a list of 301 politicians. Then every KMT term is swapped with the matching DPP term. The content stays the same, and only the party labels are reversed. An unbiased labeller should give the swapped article's DPP the score it gave the original's KMT.

```math
\text{label effect} = \tfrac12\big[(s'_{\text{DPP}} - s_{\text{KMT}}) + (s_{\text{DPP}} - s'_{\text{KMT}})\big] \qquad (6.1)
```

Here $s$ is the original score and $s'$ the swapped one. A positive value favours the DPP label and a negative one the KMT label.

| Model | Label effect | 95% interval | Articles |
|---|---:|---|---:|
| Gemini 3.8 Flash (teacher) | −0.07 | [−0.10, −0.03] | 478 |
| gpt-oss-120b | +0.01 | [−0.03, +0.05] | 465 |
| Llama 4 Maverick | −0.06 | [−0.11, −0.02] | 486 |

**Table 6.1.** Party-swap test ([docs/swap-test.md](docs/swap-test.md), [docs/jury-agreement.md](docs/jury-agreement.md)).

The teacher gives the same content about 0.07 points more when it is labelled KMT. This is real but small: the outlets are about 2 points apart (Table 10.1).

### 6.3 Other models

On the same 2,836 articles, agreement on individual articles is moderate. Krippendorff's α between all four models is 0.65 for KMT and 0.71 for DPP. The ranking of outlets, however, is nearly the same: the rank correlation with the teacher is 0.99 for Gemini 3.5 Flash-Lite, 0.96 for gpt-oss and 0.98 for Llama 4. The two ends, FTV News and SET News against China Times and United Daily News, are the same for every model.

Some outlets do depend on the model. Liberty Times is clearly DPP-leaning under Gemini (−0.50) and near the middle under gpt-oss (−0.06). PTS is near the middle under Gemini (+0.02) and DPP-leaning under Llama 4 (−0.44).

Articles where the three main models disagree by 2 points or more are listed in [docs/jury-disagreements.md](docs/jury-disagreements.md). They are 4% of KMT judgements and 3% of DPP judgements.

### 6.4 A reworded prompt

On 595 articles, the codebook was given with different wording, the party order reversed and the scale described from positive to negative. The teacher barely changed: α was 0.84–0.96 and the outlet ranking correlation 0.99. The open models changed more (rank correlations 0.85 and 0.81), about as much as they differ from each other ([docs/prompt-sensitivity.md](docs/prompt-sensitivity.md)).

### 6.5 A method without any language model

Following Gentzkow & Shapiro (2010), we found the words that most separate KMT from DPP legislators in parliamentary questions, and counted which side's words each outlet uses. It sorted press releases correctly, but its outlet ranking disagreed between legislative terms and with the LLM (rank correlations −0.08 to 0.53). We report it as a weak check only ([docs/phrase-baseline-comparison.md](docs/phrase-baseline-comparison.md)).

---

## 7. Trends over time

For each outlet and party, the monthly mean stance $y_t$ is treated as a noisy reading of a slowly moving true level $\mu_t$:

```math
\mu_t = \mu_{t-1} + \eta_t,\quad \eta_t \sim N(0,\ \tau^2 \cdot \text{jump}_t); \qquad y_t = \mu_t + \varepsilon_t,\quad \varepsilon_t \sim N(0,\ v_t) \qquad (7.1)
```

- $v_t$ is the variance of the month's mean: the spread between articles divided by their number. Months with few articles get wide intervals.
- $\tau$ is chosen by maximum likelihood.
- A Kalman filter and RTS smoother give the exact mean and 95% interval for every month, and months without articles are bridged.

**Known events.** $\text{jump}_t = 1$ except in months with a known event, where it is 25. In those months the model allows a step five times the usual size, but does not say which way or whether one happens. The events come from fixed rules in `config/events.yaml`: the change of government on 20 May 2016, a change of controlling owner, and a new chair at outlets without a controlling shareholder.

Removing the events changes no outlet's overall ranking (rank correlation 1.00), and no monthly mean by more than 0.07 ([docs/trend-model.md](docs/trend-model.md)). A version without events is kept for the planned study of money flows, so that steps found there cannot be blamed on the model.

---

## 8. Watching the 2026 election

### 8.1 Weekly drift check

Articles published after the model was trained could differ from its training data, for example because of new candidates or new topics. Every week during the campaign, about 5 live articles per outlet per day go to the teacher, and the model is compared with the teacher on those articles. The alert thresholds were set before the first week: |shift| > 0.10 or slope < 0.70. Action is taken only after two alerts in a row.

| Week | Party | Articles | Shift | Slope | Alert |
|---|---|---:|---:|---:|---|
| 28 Oct – 2 Nov (test split only) | KMT | 44 | +0.163 | 0.77 | yes |
| | DPP | 54 | −0.168 | 0.86 | yes |
| 3 – 6 Nov | KMT | 170 | +0.033 | 0.80 | no |
| | DPP | 186 | +0.001 | 0.86 | no |
| 7 – 9 Nov | KMT | 133 | +0.146 | 0.68 | yes |
| | DPP | 145 | −0.018 | 0.80 | no |

**Table 8.1.** Drift on live articles ([docs/drift-monitor.md](docs/drift-monitor.md)).

The model reads live KMT coverage about 0.1 points more favourably than the teacher does. Refitting the calibration on the live weeks was tested by holding out each week in turn. It did not reduce the shift in the held-out week, so it was not applied (§9). The next weekly batch decides whether the alert repeats.

### 8.2 The step at the data boundary

Most outlets' KMT scores step up between September (historical sample) and October 2026 (live collection). [docs/source-switch.md](docs/source-switch.md) splits the step into three parts:

| Cause | Size (median across outlets) |
|---|---|
| Whole step, KMT, politics section only | +0.21 (DPP +0.03) |
| The model is more lenient to the KMT than the teacher on live articles | +0.10 (DPP −0.05) |
| The usual pre-election rise, the same months in 2014 / 2018 / 2022 | +0.09 / +0.12 / +0.12 |
| Other sections in the live feed | matters mostly for United Daily News |

**Table 8.2.** Why the trends step up at the boundary.

Most of the step across this boundary is therefore explained by the data and the model. The website says so next to the charts. The historical sample is now also being drawn for October 2026, so the two ways of collecting can be compared on the same month.

---

## 9. What did not work

| Idea | Result | Our explanation |
|---|---|---|
| Decision model v0, raw expected stance | slope 0.45–0.57; cells shifted by −0.18 to −0.21 | Expected values pull toward the middle, and noise in the teacher's labels flattens the slope. Rebalancing the data did not fix it; calibration did (v1). |
| Calibrating by predicting the teacher from the model | the slope got smaller | That fit minimises error on each article and so shrinks averages toward the mean. We use the inverse fit (5.2). |
| TPP stance from the decision model | slope 0.51 before calibration; errors on single articles of 0.66 after | Too few training articles mention the TPP. TPP stays with the LLM labels. |
| Word-based method as an outlet ranking | rankings disagree between legislative terms (−0.22 to 0.50) | Written questions carry few partisan words, news is short, and character n-grams are coarse. Kept as a weak check. |
| Refitting the stance calibration on live weeks | held-out shift unchanged or worse | The live shift varies from week to week; a fixed linear map cannot follow it. |
| Gemini 3.5 Flash-Lite as a juror | only 78% of press releases correct | Used only for ranking checks. |
| Facebook, Threads, Dcard, TikTok | not collected | Login walls, robots.txt bans, bot checks, or research access limited to other regions or to institutions. We did not get around any of them. |

**Table 9.1.** Ideas we tested and rejected.

---

## 10. Results

The website shows every outlet and party month by month, with intervals and events: **https://chih-kai-wang.github.io/tw-media-lean/**. Table 10.1 summarises it.

| Outlet | 2012–15 | 2016–19 | 2020–23 | 2024 – Sep 2026 |
|---|---:|---:|---:|---:|
| FTV News 民視 | −0.37 | −0.76 | −0.99 | −1.36 |
| SET News 三立 | −0.78 | −0.67 | −0.66 | −0.89 |
| Liberty Times 自由時報 | −0.73 | −0.37 | −0.38 | −0.50 |
| CNA 中央社 | +0.06 | −0.23 | −0.29 | −0.23 |
| Mirror Media 鏡週刊 | — | +0.00 | −0.10 | −0.16 |
| PTS 公視 | −0.15 | −0.02 | −0.04 | −0.01 |
| TVBS | −0.20 | +0.07 | +0.16 | +0.18 |
| EBC News 東森 | — | +0.03 | +0.23 | +0.22 |
| ETtoday | −0.05 | +0.15 | +0.32 | +0.26 |
| United Daily News 聯合報 | −0.15 | +0.22 | +0.36 | +0.39 |
| China Times 中國時報 | +0.14 | +0.47 | +0.73 | +0.64 |
| The Storm Media 風傳媒 | −0.07 | +0.17 | +0.60 | +0.64 |

**Table 10.1.** KMT score minus DPP score (positive: the KMT is presented more favourably). Each value is the smoothed monthly mean, weighted by articles, from the decision model v1 trend fit of 11 November 2026. The fit covers 117,728 political articles mentioning the KMT and 130,392 mentioning the DPP. "—" means fewer than 30 articles. The last column stops at September 2026, before the data boundary of §8.2. United Daily News 2012–15 covers 2015 only. FTV News changes source between 2017 (Internet Archive) and 2019 (its own site), and its score drops by about 0.6 across that gap; how much of the drop is the change of source is not yet known.

**CTi News**, January to September 2026: KMT +0.03, DPP −0.45, gap +0.48 (1,435 articles mentioning the KMT), between United Daily News and The Storm Media in the same months, and with the same pattern of a neutral KMT score and a negative DPP score. CTi has no politics section, so its sample is political articles from its main-news section (§3.1). The teacher has not yet labelled any CTi articles; the weekly drift check will include them from the next batch.

Read the table with these points in mind:

- **It is a position on a defined scale**: how favourably articles present each party, as judged by a language model. It measures presentation only.
- **The labels come from one LLM**, checked as in §6. The ranking holds across four models, but some outlets depend on the model, for example Liberty Times and PTS (§6.3).
- **The labeller favours the KMT label by about 0.07** for the same content (§6.2). This is not subtracted from the table.
- **Government and opposition.** The KMT governed in 2012–15 and the DPP from 2016. Most outlets move toward the KMT after 2016, and part of that is the general tendency to criticise whoever governs.
- **Topics are not controlled.** An outlet that covers more scandals will score lower for the party involved.

### 10.1 Other patterns

[docs/findings.md](docs/findings.md) lists patterns beyond the ranking. They use the historical sample only (to September 2026), and are checked against the teacher's own labels and against a fixed set of six outlets present every year.

1. **Outlets lean mainly by covering the other party badly.** The KMT-leaning outlets are about neutral on the KMT; their gap comes almost entirely from negative DPP coverage (China Times: KMT +0.01, DPP −0.62). The DPP-leaning outlets are clearly negative on the KMT and only mildly positive on the DPP (FTV News: −1.03 and +0.33). No outlet presents the KMT clearly positively on average.
2. **The lean holds within every topic.** Giving every outlet the same mix of topics changes no outlet's gap by more than 0.05, and the outlets are about as far apart within every topic.
3. **Opinion pieces lean 1.4–3 times more than news, again through the other party.** Under the teacher's labels, most of The Storm Media's lean comes from its commentary.
4. **The outlets drew apart around 2018–2019, about three years after the 2016 change of government.** Among the six outlets, the spread of KMT − DPP was 0.3–0.4 in 2014–2017 and 0.55–0.70 from 2019.
5. **The governing party is presented worse.** The average gap moved by about 0.3 between KMT and DPP government, about 0.15 per party, gradually over several years.
6. **The model finds known events by itself.** The months in which all outlets moved together match, among others, the 2017 fight over the infrastructure budget, the August 2017 blackout and the June 2023 #MeToo cases.

Two observations did not survive the checks: a peak of polarisation in July 2025 depends on which outlets are counted, and FTV News's drop between 2017 and 2019 coincides with its change of data source (Table 10.1).

---

## 11. Not done yet

- **Money flows (Method F).** Government procurement, government advertising, political donations and ownership records are collected ([docs/money-sources.md](docs/money-sources.md)). One finding so far: these media companies made no corporate political donations in the open records, while candidates and parties paid them about NT$638 million in 2016–2025, mostly for advertising. The event study linking money to coverage is planned for January 2027.
- **Release of the model and data** on Hugging Face, and a technical report.
- **TPP scores** from the decision model.
- **Social platforms** in the results.

---

## Appendix A. Reproducing the results

**Install.** Install [uv](https://docs.astral.sh/uv/) (Python 3.12+), then:

```bash
uv sync                  # collection and analysis
uv sync --extra train    # also the decision model (PyTorch, transformers)
uv run pytest
```

**Collect.**

```bash
uv run twmedia collect                    # live: news sites, YouTube, PTT, LINE TODAY
uv run twmedia history cna ltn ettoday    # monthly historical sample; resumable
uv run twmedia status
```

Records go to `data/raw/<source>/<YYYY-MM-DD>.jsonl`. The `data/` folder is not in git, and article text is not redistributed. YouTube needs `YOUTUBE_API_KEY` in `.env`.

**Label.** This step needs a Google Cloud project with Vertex AI; the project settings go in `.env` (see `scripts/vertex_batch.py`).

```bash
uv run python scripts/vertex_batch.py build history
uv run python scripts/vertex_batch.py submit history
uv run python scripts/vertex_batch.py fetch history
```

**Train and score.** Training was run on a Kaggle GPU.

```bash
python scripts/train_decision_model.py --base ckiplab/bert-base-chinese --epochs 3
uv run --extra train python scripts/calibrate_stance.py data/models/tw-media-lean-v1
uv run --extra train python scripts/predict_decision_model.py --model data/models/tw-media-lean-v1 --sources "hist_*" --political-only
uv run --extra train python scripts/predict_decision_model.py --model data/models/tw-media-lean-v1 --sources "news_*"
```

**Trends and website.**

```bash
uv run python scripts/fit_trends.py --labels model
uv run python scripts/fit_trends.py --labels model --period week --since 2026-08-01
uv run python scripts/export_site.py      # writes docs/assets/trends.json
```

The website is the single file `docs/index.html`, served by GitHub Pages. To preview it locally, run `python3 -m http.server --directory docs`.

## Appendix B. Where each part lives in the code

| Section | Files |
|---|---|
| §3 collection | `src/twmedia/collectors/` (`news.py`, `history.py`, `youtube.py`, `ptt.py`, `line_today.py`), `src/twmedia/http.py`, `config/sources.yaml` |
| §4 labelling | `src/twmedia/annotate.py` (prompt from the codebook), `scripts/vertex_batch.py` |
| §5 decision model | `scripts/train_decision_model.py`, `calibrate_stance.py`, `predict_decision_model.py`, `compare_model_cells.py` |
| §6 checks | `scripts/swap_test.py`, `compare_jurors.py`, `compare_prompts.py`, `jury_disagreements.py`, `phrase_baseline.py`, `report_bulk.py`; `config/politicians.yaml` |
| §7 trends | `src/twmedia/trend.py`, `scripts/fit_trends.py`, `config/events.yaml` |
| §8 election | `scripts/monitor_drift.py`, `recalibrate_stance.py`, `check_source_switch.py` |
| §10 website | `scripts/export_site.py`, `docs/index.html` |
| §10.1 other patterns | `scripts/findings.py` |
| §11 money | `scripts/money/` |

**Technical settings.** BERT base Chinese (CKIP), maximum 512 characters, 3 epochs, learning rate 3 × 10⁻⁵, batch 16. LLM labels come from Vertex AI batch prediction with JSON output. The trend model uses a Kalman filter and RTS smoother, with $\tau$ chosen on a grid by marginal likelihood and an event variance multiplier of 25.

## Appendix C. How the project was run

The project was carried out by AI coding agents (Claude Code sessions) under the supervision of the human owner, who set the goals, approved spending and public actions, and made the final decisions. Pass criteria and alert thresholds were written down before the results they judge (§5.3, §8.1). Day-to-day records are in [PLAN.md](PLAN.md) and the files in [docs/](docs/).

## Licence and data use

The code is under the [MIT licence](LICENSE). The derived data and model will carry their own licences when released. Article text is not redistributed. United Daily News reserves AI uses in its robots.txt; it is included as non-commercial academic research and disclosed here. Privacy policy: [docs/privacy.md](docs/privacy.md).

## References

- Gentzkow, M. & Shapiro, J. (2010). What drives media slant? *Econometrica*.
- Gentzkow, M., Shapiro, J. & Taddy, M. (2019). Measuring group differences in high-dimensional choices. *Econometrica*.
- Di Tella, R. & Franceschelli, I. (2011). Government advertising and media coverage of corruption scandals. *AEJ: Applied*.
- Gilardi, F., Alizadeh, M. & Kubli, M. (2023). ChatGPT outperforms crowd workers for text-annotation tasks. *PNAS*.
- Martin, A. & Quinn, K. (2002). Dynamic ideal point estimation via MCMC. *Political Analysis*.
- Reuters Institute, [Digital News Report 2026: Taiwan](https://reutersinstitute.politics.ox.ac.uk/digital-news-report/2026/taiwan).

---

<a id="繁體中文"></a>

# 台灣新聞媒體如何呈現國民黨與民進黨（2012–2026）

**公開、可重現的研究 · 程式碼、方法與初步結果 · [網站](https://chih-kai-wang.github.io/tw-media-lean/)**

> **狀態（2026 年 11 月 12 日）**：這是初步結果。2026 年九合一選舉（11 月 28 日投票）的觀測持續到 12 月 28 日；決策模型重新校準後（第 8 節），選舉期間的數字可能改變。分數描述的是新聞怎麼呈現各政黨。

## 摘要

本專案量化台灣 12 家新聞媒體 2012 至 2026 年間每個月如何呈現國民黨與民進黨，附不確定區間，只用公開資料與任何人都能重跑的方法。

大型語言模型（LLM）Gemini 3.8 Flash 在看不到媒體名稱的情況下讀約 1.4 萬篇文章，替每個政黨打 −2（很負面）到 +2（很正面）的分數。接著訓練一個小型中文模型模仿這些分數，由它替其餘文章評分：目前共 269,609 篇，其中 190,144 篇是政治新聞。最後用隨機漫步模型平滑每家媒體的月平均。

標籤用幾種方式檢查。各黨自己的新聞稿應該被判為對自己有利，實際上國民黨新聞稿判對 90%、民進黨新聞稿判對 94%。把文章中的黨名對調，分數應該跟著對調，剩下的偏差是 4 分量尺上的 0.07 分。另外三個不同公司的模型對媒體的排序幾乎相同（排名相關 0.96–0.99）。

各媒體的位置從民視（2024–26 年民進黨較受正面呈現，差 1.36 分）分布到中國時報與風傳媒（國民黨較受正面呈現，差 0.64 分）。

## 目錄

1. [前言](#1-前言)
2. [背景知識](#2-背景知識)
3. [資料](#3-資料)
4. [用語言模型標註](#4-用語言模型標註)
5. [決策模型](#5-決策模型)
6. [標籤的檢驗](#6-標籤的檢驗)
7. [隨時間的變化](#7-隨時間的變化)
8. [觀測 2026 年選舉](#8-觀測-2026-年選舉)
9. [沒有用的做法](#9-沒有用的做法)
10. [結果](#10-結果)
   - [10.1 其他規律](#101-其他規律)
11. [還沒完成的部分](#11-還沒完成的部分)
- [附錄 A 重現結果](#附錄-a-重現結果)
- [附錄 B 各部分在程式碼中的位置](#附錄-b-各部分在程式碼中的位置)
- [附錄 C 專案的運作方式](#附錄-c-專案的運作方式)
- [授權與資料使用](#授權與資料使用)
- [參考文獻](#參考文獻)

---

## 1. 前言

### 1.1 問題

台灣讀者常說某家媒體「偏藍」或「偏綠」，但這些說法很少被量測過。本專案問一個較窄、可以量測的問題：

> 在提到某個政黨的文章裡，這個政黨被呈現得多正面或多負面？2012 年以來有什麼變化？

兩個政黨各自評分，各有一條量尺。一家媒體可能對兩黨都嚴厲，也可能對兩黨都友善。民眾黨也有標註，但它的分數還不夠可靠，暫不公開（第 5.3 節）。

### 1.2 為什麼難

1. **沒有標準答案。** 沒有人替數十萬篇台灣新聞，就各政黨被呈現的方式打過分。
2. **規模。** 12 家媒體、15 年的文章，多到不可能全部讀完，也無法以合理成本全部送給大型模型。
3. **存檔不完整。** 各家保留舊文章的時間不同，Internet Archive 也只存了一部分，所以有些媒體晚於 2012 年才有資料（表 3.1）。
4. **誰執政有影響。** 執政黨是多數政策新聞的主角，也承受多數批評。2016 年 5 月以前由國民黨執政，之後由民進黨執政，所以跨過 2016 年的變化，一部分反映的是政黨輪替。

### 1.3 我們的做法

```
     新聞網站，2012–2026                       政黨新聞稿
  （每月隨機抽樣＋即時收集）                  （已知立場：錨點）
                 │                                   │
                 ▼                                   │
   LLM 標註約 1.4 萬篇  ◄────────────────────────────┘
   （看不到媒體名稱，固定的標註規則）
                 │                      檢驗：錨點、政黨對調、
                 │                      另外三個 LLM、改寫提示詞、
                 ▼                      不用 LLM 的用語方法
   小型中文模型學著模仿 LLM
                 │
                 ▼
   替所有抽樣文章評分（269,609 篇）
                 │
                 ▼
   隨機漫步模型平滑每個「媒體 × 政黨 × 月」，
   附 95% 區間與已知事件（政黨輪替、經營者變更）
                 │
                 ▼
   網站、資料檔、報告
```

---

## 2. 背景知識

**立場。** 每篇文章對提到的每個政黨，標一個 −2（強烈負面）到 +2（強烈正面）的整數，0 表示中立或正負平衡。規則在 [docs/codebook.md](docs/codebook.md)。最重要的原則是：標的是文章怎麼呈現該黨：平實報導一件醜聞、並給該黨回應空間，是 −1；用帶情緒的字眼、只呈現單方說法，才是 −2。

**媒體分數。** 某家媒體在某段期間對某黨的分數，是它提到該黨的文章的平均立場。下文使用的摘要是「國民黨分數減民進黨分數」：正值表示國民黨被呈現得比民進黨正面。

**用語言模型標註。** 大型語言模型能照著寫好的標註規則判斷文字，成本只有人工標註的一小部分（Gilardi et al., 2023）。它也可能帶有自己的偏誤，所以才有第 6 節。

**蒸餾。** 每篇文章都送給大型模型，每次都要花錢。改用大型模型的標籤訓練一個小模型（BERT，約 1 億個參數）。小模型之後執行不用花錢，同一篇文章每次也給出相同答案。

**校準。** 這樣訓練出來的模型，分數容易被拉向中間。校準是擬合一條直線，把小模型的分數對回大型模型的量尺（第 5.2 節）。

---

## 3. 資料

### 3.1 媒體

| 媒體 | 最早資料 | 歷史資料來源 |
|---|---|---|
| 中央社 | 2012 | 自家網站；2014-07 以前用 Internet Archive |
| 自由時報 | 2012 | 自家網站 |
| 聯合報 | 2015 | Internet Archive（2015 年以前的路徑被聯合報的 robots.txt 排除） |
| 中國時報 | 2012 | 自家網站 |
| ETtoday | 2012 | 自家網站 |
| TVBS | 2013 | 自家網站 |
| 三立 | 2013-10 | 自家網站 |
| 民視 | 2012 | 2017 年以前用 Internet Archive；2019 年起用自家網站；缺 2018 年 |
| 東森 | 2018-03 | 自家網站 |
| 公視 | 2012 | 自家網站 |
| 風傳媒 | 2014 | 自家網站 |
| 鏡週刊 | 2016-11 | Internet Archive |
| 中天（2026-11-12 加入） | 2026-01 | 自家網站的每月 sitemap；沒有政治版，從「要聞」版抽政治新聞；更早的年份正在檢查 Internet Archive |

**表 3.1** 各家媒體。中天於 2026 年 11 月 12 日加入，只有 2026 年 1 月起的資料，所以出現在網站與第 10 節，表 10.1 沒有它；中天新聞台在 2020 年 12 月失去執照，中天新聞網的文章清單只回溯到 2026 年 1 月。細節見 [docs/collection-status.md](docs/collection-status.md) 與 [docs/archive-url-schemes.md](docs/archive-url-schemes.md)。

### 3.2 兩種收集方式

- **歷史抽樣（到 2026 年 9 月）**：每家媒體每個月隨機抽至多 300 篇政治新聞。各月份輪流抽，中途停止時，各月仍平均分布。
- **即時收集（2026 年 10 月 31 日起）**：每小時從各家 sitemap 讀取最新文章，各版面都收。

兩種方式收到的文章不同，第 8.2 節說明這對趨勢的影響。

社群平台（YouTube、PTT、LINE TODAY）也有收集，但還沒放進結果。

### 3.3 收集原則

- 使用誠實的 User-Agent，遵守 robots.txt，每個網站每秒至多一個請求。
- 不登入，也不繞過封鎖或機器人驗證；被封鎖的來源就停止收集。
- robots.txt 標示 `ai-train=no` 的來源（PTT、中央社）可以標註與評分，但不用來訓練模型。
- 不轉載新聞全文，只公開網址、標題、標籤與彙總結果。討論平台的帳號一律雜湊（[docs/privacy.md](docs/privacy.md)）。

---

## 4. 用語言模型標註

每篇文章連同固定的標註規則（[docs/codebook.md](docs/codebook.md)）送給模型，不附媒體名稱。模型回傳 JSON，內容包括：

- 這篇是否與台灣政治有關；
- 文章類型與主要議題；
- 三個政黨各自是否被提及、份量（0–3）、是否直接引述該黨人士、立場（−2 到 +2）。

**為什麼用語言模型。** 作者沒有自己動手標註，原因有兩個：作者擔心自己的標註會帶入個人的主觀政治傾向，而這正是本研究要量測的東西；一個人的人力也不足以標註數萬篇文章。因此改用語言模型，並找來不同公司、不同家族的模型，彼此對照檢查。

主要的標註模型（下稱「老師」）是 **Gemini 3.8 Flash**，以 Google Cloud Vertex AI 批次工作執行。它標了 13,920 篇新聞與新聞稿作為訓練資料，在各媒體與各時期之間平衡抽樣。選舉期間，它每週也標一批即時文章（第 8.1 節）。

另外三個模型標了同一批 2,836 篇作為檢驗（第 6.3 節）：Gemini 3.5 Flash-Lite（Google）、gpt-oss-120b（OpenAI，開放權重）、Llama 4 Maverick（Meta，開放權重）。研究設計允許至多一個中國公司的模型，但當時 Vertex AI 上沒有可用的，所以沒有納入。

---

## 5. 決策模型

### 5.1 架構

決策模型是 `ckiplab/bert-base-chinese`，每個標註問題接一個小分類頭，讀每篇文章的前 512 字。訓練 3 輪，訓練集 11,106 篇、驗證集 1,342 篇，另留 1,472 篇當測試集，依文章切分。

訓練樣本依 1/√（該媒體 × 時期的篇數）加權，避免大媒體主導；立場類別也加權。每個分類頭的機率都在驗證集上做溫度校準。

### 5.2 立場量尺校準

模型對五個立場值各輸出一個機率，原始分數 $x$ 是期望值：

```math
x = \sum_{k=-2}^{2} k \, p_k \qquad (5.1)
```

在驗證集上，對每個政黨擬合原始分數與老師標籤 $t$ 的直線，再反解：

```math
x = c + d\,t \quad\Rightarrow\quad \text{校正分數} = \frac{x - c}{d} \qquad (5.2)
```

這個方向的擬合，讓校正後的分數在每個群組的平均都與老師一致，這正是媒體平均需要的。反方向的擬合（用 $x$ 預測 $t$）會讓每篇的誤差最小，但把所有平均拉向中間（第 9 節）。

### 5.3 測試結果

達標標準在訓練前就已寫下：兩黨的平均偏移都小於 0.03，斜率都大於 0.8。

| 政黨 | 篇數 | 偏移（模型 − 老師） | 斜率 | 平均絕對差 | 使用 |
|---|---:|---:|---:|---:|---|
| 國民黨 | 886 | −0.008 | 0.96 | 0.44 | 是 |
| 民進黨 | 1,028 | −0.019 | 0.93 | 0.41 | 是 |
| 民眾黨 | 183 | −0.034 | 1.17 | 0.66 | **否** |

**表 5.1** 決策模型 v1 在測試集上與老師的比較（[docs/decision-model.md](docs/decision-model.md)）。

民眾黨不使用：測試文章只有 183 篇，校準時量尺要放大將近三倍，單篇誤差變得很大。

在兩黨各至少 30 篇的「媒體 × 時期」格子上（38 格），模型的「國民黨 − 民進黨」與老師的排名相關為 0.96，平均絕對差 0.15，整體偏移 −0.01。單篇分數的雜訊比老師大，這個模型是用來算數百篇文章的平均。

---

## 6. 標籤的檢驗

標籤用任何人都能重跑的方式檢驗。

### 6.1 已知立場錨點

政黨自己的新聞稿應該對自己正面。2012–2026 年間，老師把 996 篇國民黨新聞稿中的 893 篇（90%）、988 篇民進黨新聞稿中的 924 篇（94%）判為對自己黨正面，兩黨執政期都是如此（[docs/bulk-annotation.md](docs/bulk-annotation.md)）。新聞稿比新聞立場鮮明，所以這是準確率的上限。

### 6.2 政黨對調測試

先用 301 位政治人物的名單，把人名換成帶黨籍的代號（例如「國民黨籍人士甲」），再把所有國民黨字詞與對應的民進黨字詞互換。內容不變，只有黨派標籤相反。沒有偏誤的標註者，對調版給民進黨的分數，應該等於原版給國民黨的分數。

```math
\text{標籤效應} = \tfrac12\big[(s'_{\text{DPP}} - s_{\text{KMT}}) + (s_{\text{DPP}} - s'_{\text{KMT}})\big] \qquad (6.1)
```

其中 $s$ 是原版分數，$s'$ 是對調版分數。正值表示偏向民進黨標籤，負值表示偏向國民黨標籤。

| 模型 | 標籤效應 | 95% 區間 | 篇數 |
|---|---:|---|---:|
| Gemini 3.8 Flash（老師） | −0.07 | [−0.10, −0.03] | 478 |
| gpt-oss-120b | +0.01 | [−0.03, +0.05] | 465 |
| Llama 4 Maverick | −0.06 | [−0.11, −0.02] | 486 |

**表 6.1** 政黨對調測試（[docs/swap-test.md](docs/swap-test.md)、[docs/jury-agreement.md](docs/jury-agreement.md)）。

同樣的內容標成國民黨時，老師平均多給約 0.07 分。這個偏誤確實存在但很小：各媒體之間相差約 2 分（表 10.1）。

### 6.3 其他模型

在同一批 2,836 篇上，逐篇的一致程度中等：四個模型的 Krippendorff's α，國民黨 0.65、民進黨 0.71。但媒體排序幾乎相同：與老師的排名相關，Gemini 3.5 Flash-Lite 0.99、gpt-oss 0.96、Llama 4 0.98。兩端（民視、三立對中國時報、聯合報）在每個模型下都一樣。

有些媒體的位置取決於模型。自由時報在 Gemini 下明顯偏民進黨（−0.50），在 gpt-oss 下接近中間（−0.06）；公視在 Gemini 下接近中間（+0.02），在 Llama 4 下偏民進黨（−0.44）。

三個主要模型意見相差 2 分以上的文章列在 [docs/jury-disagreements.md](docs/jury-disagreements.md)，占國民黨判斷的 4%、民進黨判斷的 3%。

### 6.4 改寫提示詞

在 595 篇文章上，把標註規則換一種措辭、政黨順序倒過來、量尺改為由正到負描述。老師幾乎不受影響：α 0.84–0.96，媒體排名相關 0.99。開源模型變動較大（排名相關 0.85 與 0.81），幅度和它們彼此之間的差異相近（[docs/prompt-sensitivity.md](docs/prompt-sensitivity.md)）。

### 6.5 不用任何語言模型的方法

仿照 Gentzkow & Shapiro (2010)，從立委質詢中找出最能區分國民黨與民進黨立委的詞，再數各媒體較常用哪一邊的詞。它能正確區分新聞稿，但對媒體的排序在不同屆期之間不一致，與 LLM 的排名相關也只有 −0.08 到 0.53。因此只當作弱檢查（[docs/phrase-baseline-comparison.md](docs/phrase-baseline-comparison.md)）。

---

## 7. 隨時間的變化

每家媒體、每個政黨的月平均立場 $y_t$，視為一個緩慢移動的真實水準 $\mu_t$ 加上雜訊：

```math
\mu_t = \mu_{t-1} + \eta_t,\quad \eta_t \sim N(0,\ \tau^2 \cdot \text{jump}_t); \qquad y_t = \mu_t + \varepsilon_t,\quad \varepsilon_t \sim N(0,\ v_t) \qquad (7.1)
```

- $v_t$ 是該月平均的變異數：文章之間的離散程度除以篇數。文章少的月份，區間較寬。
- $\tau$ 以最大概似選出。
- 用卡爾曼濾波加 RTS 平滑，求出每個月的精確平均與 95% 區間；沒有文章的月份由隨機漫步銜接。

**已知事件。** $\text{jump}_t$ 平常是 1，有已知事件的月份是 25。這些月份允許的變動是平常的 5 倍，但不指定方向，也不保證會有變動。事件依 `config/events.yaml` 的固定規則選出：2016 年 5 月 20 日政黨輪替、控制者變更，以及沒有控制股東的媒體更換董事長。

拿掉事件後，各媒體的整體排序不變（排名相關 1.00），任何一個月的平均變動都不超過 0.07（[docs/trend-model.md](docs/trend-model.md)）。不含事件的版本另外保留，給之後的資金關聯分析使用，這樣在那裡找到的變化不能歸咎於模型。

---

## 8. 觀測 2026 年選舉

### 8.1 每週漂移檢查

模型訓練之後才刊出的文章，可能和訓練資料不同，例如出現新的候選人或新的議題。選戰期間每週從即時文章中，每家媒體每天抽約 5 篇給老師標註，在同一批文章上比較模型與老師。警示門檻在第一週之前就已訂定：偏移絕對值大於 0.10，或斜率小於 0.70。連續兩週超過門檻才處理。

| 週 | 政黨 | 篇數 | 偏移 | 斜率 | 警示 |
|---|---|---:|---:|---:|---|
| 10/28–11/02（僅測試切分） | 國民黨 | 44 | +0.163 | 0.77 | 是 |
| | 民進黨 | 54 | −0.168 | 0.86 | 是 |
| 11/03–11/06 | 國民黨 | 170 | +0.033 | 0.80 | 否 |
| | 民進黨 | 186 | +0.001 | 0.86 | 否 |
| 11/07–11/09 | 國民黨 | 133 | +0.146 | 0.68 | 是 |
| | 民進黨 | 145 | −0.018 | 0.80 | 否 |

**表 8.1** 即時文章上的漂移（[docs/drift-monitor.md](docs/drift-monitor.md)）。

在即時新聞上，模型給國民黨的分數比老師高約 0.1 分。我們測試過用即時批次重新擬合校準，每次留下一週當測試；被留下那週的偏移沒有縮小，所以沒有套用（第 9 節）。下一批每週資料會決定警示是否連續出現。

### 8.2 資料分界上的跳動

多數媒體的國民黨分數，在 2026 年 9 月（歷史抽樣）到 10 月（即時收集）之間往上跳。[docs/source-switch.md](docs/source-switch.md) 把這個跳動拆成三部分：

| 原因 | 幅度（各媒體中位數） |
|---|---|
| 整體跳動，國民黨，只看政治版 | +0.21（民進黨 +0.03） |
| 在即時文章上，模型對國民黨比老師寬鬆 | +0.10（民進黨 −0.05） |
| 歷年選前的固定上升，2014／2018／2022 同月份 | +0.09／+0.12／+0.12 |
| 即時收集包含其他版面 | 主要影響聯合報 |

**表 8.2** 趨勢在分界上往上跳的原因。

所以跨過這個分界的變化，大部分可以由資料與模型解釋。網站在圖旁註明了這一點。目前也正用歷史抽樣補抽 2026 年 10 月，以便在同一個月比較兩種收集方式。

---

## 9. 沒有用的做法

| 做法 | 結果 | 我們的解釋 |
|---|---|---|
| 決策模型 v0，直接用立場期望值 | 斜率 0.45–0.57；格子整體偏移 −0.18 到 −0.21 | 期望值會被拉向中間，老師標籤的雜訊也讓斜率變平。重新平衡資料沒有解決，校準才解決（v1）。 |
| 用模型分數預測老師分數來校準 | 斜率反而變小 | 這種擬合讓每篇的誤差最小，所以會把平均往中間壓。改用反向擬合（式 5.2）。 |
| 用決策模型給民眾黨立場 | 校準前斜率 0.51；校準後單篇誤差 0.66 | 提到民眾黨的訓練文章太少。民眾黨維持用 LLM 標籤。 |
| 用語方法排序媒體 | 不同屆期的排序互相矛盾（−0.22 到 0.50） | 書面質詢的黨派用語少、新聞篇幅短、字元 n-gram 太粗。保留為弱檢查。 |
| 用即時批次重新擬合立場校準 | 被留下那週的偏移不變或更大 | 即時文章的偏移每週不同，固定的直線跟不上。 |
| 讓 Gemini 3.5 Flash-Lite 當陪審員 | 新聞稿只判對 78% | 只用來檢驗排序，不列入陪審團。 |
| Facebook、Threads、Dcard、TikTok | 沒有收集 | 登入牆、robots.txt 禁止、機器人驗證，或研究管道只開放給其他地區或學術機構。我們沒有繞過任何一項。 |

**表 9.1** 測試過但放棄的做法。

---

## 10. 結果

網站逐月呈現每家媒體、每個政黨的分數，附區間與事件：**https://chih-kai-wang.github.io/tw-media-lean/**。表 10.1 是摘要。

| 媒體 | 2012–15 | 2016–19 | 2020–23 | 2024–2026/09 |
|---|---:|---:|---:|---:|
| 民視 | −0.37 | −0.76 | −0.99 | −1.36 |
| 三立 | −0.78 | −0.67 | −0.66 | −0.89 |
| 自由時報 | −0.73 | −0.37 | −0.38 | −0.50 |
| 中央社 | +0.06 | −0.23 | −0.29 | −0.23 |
| 鏡週刊 | — | +0.00 | −0.10 | −0.16 |
| 公視 | −0.15 | −0.02 | −0.04 | −0.01 |
| TVBS | −0.20 | +0.07 | +0.16 | +0.18 |
| 東森 | — | +0.03 | +0.23 | +0.22 |
| ETtoday | −0.05 | +0.15 | +0.32 | +0.26 |
| 聯合報 | −0.15 | +0.22 | +0.36 | +0.39 |
| 中國時報 | +0.14 | +0.47 | +0.73 | +0.64 |
| 風傳媒 | −0.07 | +0.17 | +0.60 | +0.64 |

**表 10.1** 國民黨分數減民進黨分數（正值：國民黨被呈現得較正面）。每個數值是平滑後的月平均，依篇數加權，取自決策模型 v1 於 2026 年 11 月 11 日的趨勢擬合；涵蓋提到國民黨的政治新聞 117,728 篇、提到民進黨的 130,392 篇。「—」表示少於 30 篇。最後一欄到 2026 年 9 月為止，在第 8.2 節的資料分界之前。聯合報 2012–15 只有 2015 年。民視在 2017 年（Internet Archive）與 2019 年（自家網站）之間換了資料來源，分數在這個缺口前後下降約 0.6；其中多少來自來源改變，目前還不知道。

**中天**，2026 年 1–9 月：國民黨 +0.03、民進黨 −0.45，差距 +0.48（提到國民黨的 1,435 篇），同期介於聯合報與風傳媒之間，型態同樣是國民黨中性、民進黨負面。中天沒有政治版，樣本取自「要聞」版中的政治新聞（第 3.1 節）。老師模型還沒標過中天的文章，下一批每週漂移檢查起會納入。

讀這張表時請注意：

- **這是在定義好的量尺上的位置**：由語言模型判斷的、文章呈現各政黨的正負程度。它只衡量呈現方式。
- **標籤來自單一 LLM**，並經過第 6 節的檢驗。排序在四個模型之間一致，但有些媒體的位置取決於模型，例如自由時報與公視（第 6.3 節）。
- **標註模型對國民黨標籤約多給 0.07 分**（第 6.2 節）。表中沒有扣除。
- **執政與在野。** 2012–15 年國民黨執政，2016 年起民進黨執政。多數媒體在 2016 年後往國民黨方向移動，其中一部分是「批評執政者」的一般傾向。
- **沒有控制議題。** 較常報導醜聞的媒體，涉事政黨的分數會較低。

### 10.1 其他規律

[docs/findings.md](docs/findings.md) 整理媒體排序以外的規律。只用歷史抽樣（到 2026 年 9 月），並用老師模型自己的標籤、以及每年都有資料的固定 6 家媒體重算檢查。

1. **傾向主要來自對另一黨的負面報導。** 偏國民黨的媒體對國民黨大約中性，差距幾乎全來自對民進黨的負面報導（中國時報：國民黨 +0.01、民進黨 −0.62）。偏民進黨的媒體對國民黨明顯負面，對民進黨只是微幅正面（民視：−1.03 與 +0.33）。沒有一家媒體對國民黨的平均是明顯正面的。
2. **傾向在每個議題裡都存在。** 讓每家媒體套用同一個議題比例，差距的變化都不超過 0.05；在每個議題裡，媒體之間的距離也差不多大。
3. **評論的傾向是新聞的 1.4 到 3 倍，同樣來自對另一黨更負面。** 老師標籤下，風傳媒的傾向大多來自評論。
4. **媒體之間的距離在 2018–2019 年拉大，比 2016 年政黨輪替晚了約三年。** 固定 6 家媒體「國民黨 − 民進黨」的標準差，2014–2017 年約 0.3–0.4，2019 年起為 0.55–0.70。
5. **執政黨被呈現得較差。** 從國民黨執政到民進黨執政，平均差距移動約 0.3，相當於每黨約 0.15 分，而且是逐年移動。
6. **模型自己找到了已知事件。** 所有媒體一起偏離的月份，對得上 2017 年前瞻條例的立法院衝突、2017 年 8 月大停電、2023 年 6 月 #MeToo 事件等。

有兩項觀察沒有通過檢查：2025 年 7 月的極化高峰取決於計入哪些媒體；民視 2017 到 2019 年間的下降與資料來源改變重疊（表 10.1）。

---

## 11. 還沒完成的部分

- **資金關聯（方法 F）。** 政府採購、政策宣導、政治獻金與所有權資料已經收集（[docs/money-sources.md](docs/money-sources.md)）。目前的一項發現：在公開紀錄中，這些媒體公司沒有營利事業政治獻金；反方向，2016–2025 年候選人與政黨付給它們約 6.38 億元，以宣傳支出為主。連結資金與報導的事件研究預計 2027 年 1 月進行。
- 在 Hugging Face **公開模型與資料**，以及技術報告。
- 決策模型的**民眾黨分數**。
- 把**社群平台**納入結果。

---

## 附錄 A 重現結果

**安裝。** 先安裝 [uv](https://docs.astral.sh/uv/)（Python 3.12 以上），然後：

```bash
uv sync                  # 收集與分析
uv sync --extra train    # 另外安裝決策模型所需（PyTorch、transformers）
uv run pytest
```

**收集。**

```bash
uv run twmedia collect                    # 即時：新聞網站、YouTube、PTT、LINE TODAY
uv run twmedia history cna ltn ettoday    # 每月歷史抽樣，中斷後可接續
uv run twmedia status
```

紀錄存在 `data/raw/<來源>/<YYYY-MM-DD>.jsonl`。`data/` 不進 git，也不轉載原文。YouTube 需要在 `.env` 設定 `YOUTUBE_API_KEY`。

**標註。** 這一步需要一個啟用 Vertex AI 的 Google Cloud 專案，專案設定寫在 `.env`（見 `scripts/vertex_batch.py`）。

```bash
uv run python scripts/vertex_batch.py build history
uv run python scripts/vertex_batch.py submit history
uv run python scripts/vertex_batch.py fetch history
```

**訓練與評分。** 訓練在 Kaggle GPU 上執行。

```bash
python scripts/train_decision_model.py --base ckiplab/bert-base-chinese --epochs 3
uv run --extra train python scripts/calibrate_stance.py data/models/tw-media-lean-v1
uv run --extra train python scripts/predict_decision_model.py --model data/models/tw-media-lean-v1 --sources "hist_*" --political-only
uv run --extra train python scripts/predict_decision_model.py --model data/models/tw-media-lean-v1 --sources "news_*"
```

**趨勢與網站。**

```bash
uv run python scripts/fit_trends.py --labels model
uv run python scripts/fit_trends.py --labels model --period week --since 2026-08-01
uv run python scripts/export_site.py      # 寫出 docs/assets/trends.json
```

網站只有一個檔案 `docs/index.html`，由 GitHub Pages 提供。要在本機預覽，執行 `python3 -m http.server --directory docs`。

## 附錄 B 各部分在程式碼中的位置

| 章節 | 檔案 |
|---|---|
| 第 3 節 收集 | `src/twmedia/collectors/`（`news.py`、`history.py`、`youtube.py`、`ptt.py`、`line_today.py`）、`src/twmedia/http.py`、`config/sources.yaml` |
| 第 4 節 標註 | `src/twmedia/annotate.py`（由標註規則產生提示詞）、`scripts/vertex_batch.py` |
| 第 5 節 決策模型 | `scripts/train_decision_model.py`、`calibrate_stance.py`、`predict_decision_model.py`、`compare_model_cells.py` |
| 第 6 節 檢驗 | `scripts/swap_test.py`、`compare_jurors.py`、`compare_prompts.py`、`jury_disagreements.py`、`phrase_baseline.py`、`report_bulk.py`；`config/politicians.yaml` |
| 第 7 節 趨勢 | `src/twmedia/trend.py`、`scripts/fit_trends.py`、`config/events.yaml` |
| 第 8 節 選舉 | `scripts/monitor_drift.py`、`recalibrate_stance.py`、`check_source_switch.py` |
| 第 10 節 網站 | `scripts/export_site.py`、`docs/index.html` |
| 第 10.1 節 其他規律 | `scripts/findings.py` |
| 第 11 節 資金 | `scripts/money/` |

**技術設定。** CKIP 的 BERT base 中文模型，最長 512 字，訓練 3 輪，學習率 3 × 10⁻⁵，批次 16。LLM 標籤來自 Vertex AI 批次預測，輸出 JSON。趨勢模型用卡爾曼濾波加 RTS 平滑，$\tau$ 以邊際概似在格點上選出，事件變異數倍數為 25。

## 附錄 C 專案的運作方式

本專案由 AI 程式代理（Claude Code 對話）在人類擁有者監督下完成；擁有者設定目標、核准花費與公開動作，並做最後決定。達標標準與警示門檻都在看到結果之前寫下（第 5.3、8.1 節）。日常紀錄在 [PLAN.md](PLAN.md) 與 [docs/](docs/) 的各份文件。

## 授權與資料使用

程式碼採 [MIT 授權](LICENSE)。衍生資料與模型公開時另行標示授權。不轉載新聞原文。聯合報在 robots.txt 中保留 AI 用途；本研究為非營利學術研究，仍納入分析，並在此揭露。隱私權政策見 [docs/privacy.md](docs/privacy.md)。

## 參考文獻

見英文版 [References](#references)。

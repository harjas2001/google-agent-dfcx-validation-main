# STT Mistranscription Detection & Dictionary Remediation Guide

**Document type:** Internal runbook  
**Maintained by:** Conversational AI Team  
**Last updated:** May 2026  
**Audience:** NLU engineers, voicebot delivery team, conversational AI specialists

---

## Overview

This guide explains how to run the **STT Analytics Toolkit** to identify words the voicebot is mishearing, and how to action the results directly in **Genesys Cloud's Custom Dictionary** to improve transcription accuracy.

The process has two stages:

```
Stage 1 — Detect                    Stage 2 — Remediate
─────────────────────────────       ─────────────────────────────────────
Run STT Mistranscription Detector   Open Genesys Cloud Admin
        ↓                                   ↓
Review confusion_map.csv            Add confirmed word pairs to
        ↓                           Speech & Text Analytics > Custom Dictionary
Confirm which variants are real
mistranscriptions
```

> **Why this matters:** The first signal of STT problems is usually a spike in no-match or escalation rates. By the time that shows up in your dashboard, the problem has already been active for days or weeks. This tool catches mistranscription patterns before they impact containment metrics.

---

## Part 1 — Running the STT Mistranscription Detector

### Prerequisites

Before running, you will need:

- Python 3.9 or higher installed on your machine
- A CSV or Excel export of voicebot utterance data from Genesys Cloud (see data format below)
- Access to the `stt-analytics-toolkit` repository

---

### Step 1 — Clone the Repository and Install Dependencies

Open a terminal and run:

```bash
git clone https://github.com/your-org/stt-analytics-toolkit.git
cd stt-analytics-toolkit

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

---

### Step 2 — Set Up Your Private Vocabulary Files

The tool uses two private configuration files to define which words to analyse. These files are **not stored in the repository** — you must create them locally.

**Create `vocab/domain_vocab.txt`**

This is the full list of domain-specific terms the tool will check against. One word per line.

```
# Copy the example file and populate it
cp vocab/domain_vocab.example.txt vocab/domain_vocab.txt
```

Then open `vocab/domain_vocab.txt` in any text editor and replace the placeholder entries with your real domain vocabulary — product names, plan types, technical terms, billing terms, and any other words specific to your voicebot's domain.

**Create `vocab/confusion_seeds.txt`**

This is a smaller subset of your domain vocabulary — specifically the words that are **short or phonetically ambiguous** and most at risk of being misheard. Examples: abbreviations, product codes, short technical terms.

```
cp vocab/confusion_seeds.example.txt vocab/confusion_seeds.txt
```

Populate it with a subset of your domain vocabulary. Avoid adding common English words here (e.g. "move", "plan", "name") as they will flood the output with false positives.

---

### Step 3 — Configure Column Mappings

Open `stt_mistranscription_detector/config.py` and verify the column names match your data export:

```python
COLUMN_CONFIG = {
    "utterance_col":  "Utterance",          # the raw transcription text
    "intent_col":     "Intent",             # the matched or failed intent
    "confidence_col": "Intent Confidence",  # confidence score (0–1 or 0–100)
    "session_col":    "Session ID",         # call or session identifier
}
```

If your Genesys Cloud export uses different column names, update these values. The tool will error clearly if a column is not found.

You can also adjust the confidence threshold:

```python
LOW_CONFIDENCE_THRESHOLD = 0.6   # utterances below this are flagged as low confidence
```

If your export uses 0–100 scoring (rather than 0–1), change this to `60.0`.

---

### Step 4 — Prepare Your Data

Place your utterance CSV or Excel export in the `data/` folder. This folder is gitignored — real data should never leave this folder.

**Required columns** in your export:

| Column | Description | Example value |
|---|---|---|
| Utterance | Raw STT transcription text | `"i want to recahrge my sim"` |
| Intent | The matched or failed intent | `"Intent_Recharge"` |
| Intent Confidence | Model confidence score | `0.74` |
| Session ID | Call or session identifier | `abc123` |

Column names are configurable — exact names don't matter as long as `config.py` matches.

---

### Step 5 — Run the Detector

```bash
python stt_mistranscription_detector/stt_mistranscription_engine.py \
  --input data/your_utterances.csv \
  --output results/
```

The tool will print progress to the console as it runs four detection signals. On a dataset of ~50,000 utterances, expect a runtime of 2–5 minutes.

**Optional flags:**

| Flag | Default | Description |
|---|---|---|
| `--input` | required | Path to your input CSV or Excel file |
| `--output` | `results/` | Directory to save output files |
| `--top` | `50` | Top N flagged words to use as confusion map seeds |

---

### Step 6 — Understand the Output Files

The tool writes six files to your output directory:

```
results/
├── confusion_map.csv                       ← KEY OUTPUT — use this for Genesys
├── master_mistranscription_candidates.csv  ← ranked list of suspect words
├── signal_1_low_confidence_words.csv       ← words appearing in low-confidence utterances
├── signal_2_oov_words.csv                  ← out-of-vocabulary words
├── signal_3_phonetic_collisions.csv        ← words that sound like domain terms
└── signal_4_intent_anomalies.csv           ← words associated with misclassified intents
```

#### How the four signals work

The tool runs four independent checks and combines their results into a ranked master list. A word that fires on multiple signals gets a higher composite score and appears higher in the output.

| Signal | What it detects |
|---|---|
| **Signal 1 — Low Confidence** | Words that appear frequently in utterances where the model had low confidence |
| **Signal 2 — Out of Vocabulary (OOV)** | Words not in standard English that are phonetically close to domain terms — likely mishearings |
| **Signal 3 — Phonetic Collision** | Words that sound like known domain vocabulary (uses Soundex + Levenshtein distance) |
| **Signal 4 — Intent Anomaly** | Words that appear consistently in misclassified or ambiguous intent contexts |

---

### Step 7 — Read the Confusion Map

`confusion_map.csv` is the primary output. Open it in Excel or Google Sheets.

**Columns:**

| Column | Description |
|---|---|
| `target_word` | The domain term that is likely being misheared |
| `mistranscription_variants` | Words the model is producing instead (comma-separated) |
| `variant_frequencies` | How often each variant appears |
| `total_variant_hits` | Total occurrences across all variants |
| `composite_score` | How high the word ranks in the master detection list |
| `example_utterances` | Real utterances containing each variant — labelled `[~variant]` |

**Example row:**

| target_word | mistranscription_variants | variant_frequencies | total_variant_hits | example_utterances |
|---|---|---|---|---|
| `esim` | `easy sim, he sim, e-sim` | `14, 9, 6` | `29` | `[~easy sim] i want to activate my easy sim card` |

**How to validate a pair:**

Before adding anything to Genesys, check the `example_utterances` column. Each example is labelled with which variant triggered it — e.g. `[~easy sim]`. Read the full utterance and ask: *does this sound like someone saying "eSIM"?* If yes, it is a real mistranscription and should be actioned. If the variant could genuinely be what the customer said, skip it.

> **Rule of thumb:** If the variant appears more than 5 times and makes phonetic sense when you say the target word out loud, add it to the dictionary.

---

### Step 8 — Run No-Match Analysis (Optional)

For a separate view of abandonment patterns in no-match traffic:

```bash
python no_match_metrics.py data/your_utterances.csv
```

This prints a breakdown of how many no-match events were caused by short (≤2 word) utterances, and whether users naturally self-corrected on their next turn. Use this to decide whether to add a reprompt to no-match handlers.

---

## Part 2 — Genesys Cloud Custom Dictionary Management

Once you have confirmed word pairs from `confusion_map.csv`, use Genesys Cloud's Custom Dictionary to boost those terms so the STT model recognises them correctly.

---

### What is the Custom Dictionary?

Genesys Cloud's Speech & Text Analytics module allows you to add **custom words** that the STT model should recognise more strongly. This is used to:

- **Boost** domain-specific terms that the default model underweights (e.g. product names, abbreviations, technical terms)
- **Add sound-alikes** so the model knows that when it hears "easy sim" in a customer service context, it should output "eSIM"

Changes take effect on new conversations after the dictionary is saved — they do not retroactively reprocess historical transcriptions.

---

### Step 1 — Navigate to the Custom Dictionary

1. Log in to Genesys Cloud
2. Go to **Admin** (top navigation)
3. Under the **Quality** section, click **Speech & Text Analytics**
4. Select the **Custom Dictionary** tab

> If you do not see this option, you may need the **Speech and Text Analytics Administrator** permission. Contact your Genesys admin.

---

### Step 2 — Add Words from the Confusion Map

For each confirmed pair in `confusion_map.csv`:

1. Click **Add Word**
2. In the **Word** field, enter the **target word** (the correct domain term — e.g. `eSIM`)
3. In the **Sounds Like** field, enter the mistranscription variant (e.g. `easy sim`)
4. Click **Save**

Repeat for each confirmed pair. You do not need to add every variant — prioritise the ones with the highest `variant_frequencies` count and the clearest phonetic match.

**Tips:**

- Add the target word exactly as it should appear in transcriptions (casing matters for some platforms — use the format your team prefers in reports)
- You can add multiple sound-alikes for the same target word by creating separate entries
- If a word only appears once or twice in the confusion map, skip it — not enough evidence

---

### Step 3 — Prioritisation Guide

Use this to decide what to action first:

| Priority | Criteria | Action |
|---|---|---|
| **High** | `total_variant_hits` > 20 AND phonetic match is obvious | Add to dictionary immediately |
| **Medium** | `total_variant_hits` 5–20 AND makes sense in context | Add to dictionary, monitor |
| **Low** | `total_variant_hits` < 5 OR context is ambiguous | Note for next cycle, don't add yet |
| **Skip** | Variant could be what the customer genuinely said | Do not add — would reduce accuracy |

---

### Step 4 — Verify and Save

After adding all confirmed pairs:

1. Review the full list of entries on the Custom Dictionary page before saving
2. Check that no common English words have been added as target words — this can cause the model to over-correct on normal speech
3. Click **Save** to publish the dictionary

Changes are applied to new conversations immediately after saving.

---

### Step 5 — Measure Improvement

After running with the updated dictionary for at least one week (or one full reporting cycle):

1. Export a fresh batch of utterance data from Genesys Cloud
2. Re-run the STT Mistranscription Detector against the new data:
   ```bash
   python stt_mistranscription_detector/stt_mistranscription_engine.py \
     --input data/post_update_utterances.csv \
     --output results/post_update/
   ```
3. Compare the new `confusion_map.csv` against the previous run:
   - The `total_variant_hits` for actioned words should have dropped
   - The `composite_score` for those words should be lower or absent
4. Also check your intent confidence distribution — low confidence rates should improve for intents that were affected by the mistranscribed terms

> If a word's variant hits have not decreased after two weeks, the variant may reflect genuine customer speech rather than a transcription error. Consider removing it from the dictionary.

---

## Quick Reference — End-to-End Checklist

```
□ Export utterance data from Genesys Cloud → save to data/
□ Populate vocab/domain_vocab.txt with domain terms
□ Populate vocab/confusion_seeds.txt with high-risk short terms
□ Verify column names in config.py match your export
□ Run: python stt_mistranscription_detector/stt_mistranscription_engine.py --input ... --output ...
□ Open results/confusion_map.csv
□ For each row: read example_utterances, say the target word out loud, decide yes/no
□ In Genesys: Admin > Speech & Text Analytics > Custom Dictionary
□ Add confirmed pairs (target word + sounds-like variant)
□ Save and publish
□ Wait one full reporting cycle
□ Re-run detector on fresh data and compare results
```

---

## Troubleshooting

| Issue | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError: domain_vocab.txt` | Vocab file not created | Copy `.example` version and populate |
| `KeyError: 'Utterance'` | Column name mismatch | Update `COLUMN_CONFIG` in `config.py` |
| Confusion map is empty | `confusion_seeds.txt` is empty or too broad | Populate with specific short domain terms |
| Too many false positives | Confusion seeds contain common English words | Remove words like "move", "plan", "name" from seeds |
| Script takes very long | Dataset is very large | Filter to a representative sample (e.g. 30 days) |
| No change after dictionary update | Dictionary not saved, or variants are genuine speech | Re-check save confirmation in Genesys; review examples again |

---

## Related Resources

- [Genesys Cloud — Custom Dictionary documentation](https://help.mypurecloud.com)
- `stt-analytics-toolkit` GitHub repository
- No-Match Metrics runbook *(link when available)*
- STT Analytics Toolkit README

---

*For questions about this process, contact the Conversational AI team.*

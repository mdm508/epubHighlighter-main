Here’s the updated **`README.md`** including the new **command-line interface (`main.py`)** usage:

---

````markdown
# 📚 EPUB Highlighter + Dictionary Builder

A Python tool and CLI app that automatically **highlights rare words** in EPUBs, **generates definitions**, **creates Anki flashcards**, and **exports to PDF** — powered by spaCy and StarDict dictionaries.

---

## 🚀 Features

- **📖 Rare word detection:** Extracts uncommon English words using [`wordfreq`](https://pypi.org/project/wordfreq/).
- **📚 StarDict integration:** Supports multiple `.ifo/.idx/.dict` dictionaries from your `dicts/` folder.
- **🧾 Glossary EPUB generation:**  
  - Inline glossaries per chapter  
  - A definitions-only EPUB (50 words per section, with mini TOCs)
- **🧠 Anki export:**  
  - Field 1 = word  
  - Field 2 = HTML definition
- **🧩 EPUB → PDF conversion:**  
  - Uses Calibre’s `ebook-convert` (optional)
- **🧪 Test mode:**  
  - Stop early (e.g., 100 words) to preview before full run
- **⚙️ CLI interface:**  
  - Configure and run via `main.py` with command-line flags.

---

## 🧩 Requirements

### Python
Tested with **Python 3.10–3.13**.

Install requirements:
```bash
pip install -r requirements.txt
````

### Dependencies

```txt
ebooklib
spacy
pystardict
wordfreq
beautifulsoup4
tqdm
lxml
html5lib
```

Install spaCy’s model (required):

```bash
python -m spacy download en_core_web_sm
```

Optional for PDF output:

```bash
sudo apt install calibre
# or download from https://calibre-ebook.com/download
```

---

## ⚙️ Configuration (inside `epub_highlighter.py`)

```python
GENERATE_HIGHLIGHTED_EPUB = True
GENERATE_DEFS_EPUB = True
GENERATE_ANKI = True
CONVERT_EPUBS_TO_PDF = False

AUTO_BUILD_WORD_LIST = True
AUTO_WORDLIST_FREQ_THRESHOLD = 3.0  # Lower = rarer words
AUTO_WORDLIST_OUTPUT = "./epub/infj-rare-words-auto.txt"

TEST_MODE = True
TEST_MAX_DEFS = 100
```

---

## 🖥 Command-Line Interface (main.py)

You can now run everything via the command line:

### 🔹 Basic usage

```bash
python main.py --epub ./epub/infj.epub --auto-wordlist
```

### 🔹 Test mode (quick sample)

```bash
python main.py --epub ./epub/infj.epub --auto-wordlist --test --test-max 100
```

### 🔹 Output to another directory

```bash
python main.py --epub ./epub/infj.epub --out-dir ./out
```

### 🔹 Generate everything including PDFs

```bash
python main.py --epub ./epub/infj.epub --auto-wordlist --pdf
```

### 🔹 Flags summary

| Flag              | Description                                                      |
| ----------------- | ---------------------------------------------------------------- |
| `--epub PATH`     | Path to the input EPUB file.                                     |
| `--out-dir DIR`   | Custom output folder.                                            |
| `--auto-wordlist` | Automatically generate rare-word list using frequency threshold. |
| `--freq VALUE`    | Frequency cutoff for auto word list (default 3.0).               |
| `--no-highlight`  | Skip highlighted book EPUB.                                      |
| `--no-defs`       | Skip definitions EPUB.                                           |
| `--no-anki`       | Skip Anki TSV export.                                            |
| `--pdf`           | Convert generated EPUBs to PDFs (needs Calibre).                 |
| `--test`          | Enable test mode (only processes first 100 defs).                |
| `--test-max N`    | Custom number of words for test mode.                            |

Example full run:

```bash
python main.py --epub ./epub/infj.epub --auto-wordlist --freq 3.0 --pdf
```

---

## 🧱 Project Layout

```
epubHighlighter/
│
├── main.py                   # CLI entry point
├── epub_highlighter.py        # main engine
├── endict.py                  # StarDict multi-loader
├── dicts/                     # .ifo/.idx/.dict dictionaries
│   ├── stardict-Oxford_English_Dictionary_2nd_Ed._P2-2.4.2/
│   ├── stardict-Oxford_Advanced_Learner_s_Dictionary-2.4.2/
│   └── ...
├── epub/
│   ├── infj.epub
│   ├── infj-highlighted.epub
│   ├── infj-definitions.epub
│   ├── infj-defs-anki.tsv
│   ├── infj-rare-words-auto.txt
│   ├── *.pdf
│   └── ...
└── requirements.txt
```

---

## 🧠 How the Pipeline Works

1. **(Optional)** Build a rare-word list with `wordfreq`:

   * Keeps only low-frequency words (below `AUTO_WORDLIST_FREQ_THRESHOLD`).
2. **Tokenize** EPUB with spaCy (`en_core_web_sm`).
3. **Match** words from the list in each chapter.
4. **Fetch** definitions via StarDict (merged from all `.ifo` files in `/dicts/`).
5. **Build:**

   * Highlighted EPUB (with inline glossaries)
   * Definitions EPUB (clean HTML, 50 words per section)
   * Anki flashcards (`TSV`)
   * Optional PDFs via Calibre.

---

## 📘 Example Output

### 🔸 Highlighted EPUB

Each chapter begins with a glossary.
Rare words are **bolded inline**.

### 🔸 Definitions EPUB

Each section = 50 definitions with nested TOC:

```
1 Abrogate
    1 Abrogate
    2 Absolution
    3 Acerbic
...
```

Words without definitions appear grouped at the bottom.

### 🔸 Anki Export

```
acolyte    <p><b>Acolyte</b> (noun): A follower or attendant, especially in a religious service.</p>
mendicant  <p><b>Mendicant</b> (adj): Given to begging; living on alms.</p>
```

---

## 🧾 License

**MIT License**
You’re free to modify and distribute with attribution.

---

## 🧰 Troubleshooting

| Issue                                               | Solution                                                                                    |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `OSError: [E050] Can't find model 'en_core_web_sm'` | Run `python -m spacy download en_core_web_sm`.                                              |
| `Dictionary file not found`                         | Check your `.ifo/.idx/.dict` files exist in `/dicts/`.                                      |
| Slow run                                            | Use `--test` first. Multiple dictionaries + large EPUBs can take minutes.                   |
| No definitions found                                | Try lowering `AUTO_WORDLIST_FREQ_THRESHOLD` or confirm your dictionaries contain that word. |
| PDFs not produced                                   | Make sure `ebook-convert` (Calibre CLI) is in PATH.                                         |

---

> 🧠 “Highlight your books, build your own dictionary, and turn them into flashcards — all in one run.”

```

---

Would you like me to add example screenshots of a generated EPUB/Anki card section (with `<img>` placeholders and captions) to the README next?
```

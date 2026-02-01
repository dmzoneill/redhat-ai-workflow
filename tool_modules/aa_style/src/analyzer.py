"""Style Analyzer - Extract writing patterns from message corpora.

Analyzes messages to extract:
- Vocabulary patterns (common words, unique phrases, technical terms)
- Sentence patterns (length, punctuation, capitalization)
- Tone markers (formality, directness, humor)
- Emoji usage (frequency, favorites, contextual patterns)
- Greetings and signoffs
- Response patterns (acknowledgment, agreement, disagreement)
"""

import re
from collections import Counter
from typing import Any


class StyleAnalyzer:
    """Analyzes writing style from a corpus of messages."""

    # Common English stop words to filter from vocabulary
    STOP_WORDS = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "been",
        "be",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "here",
        "there",
        "then",
        "if",
        "else",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "once",
        "any",
        "up",
        "down",
        "out",
        "off",
        "over",
    }

    # Common filler words/phrases
    FILLER_PATTERNS = [
        r"\blike\b",
        r"\bum\b",
        r"\buh\b",
        r"\byou know\b",
        r"\bi mean\b",
        r"\bbasically\b",
        r"\bactually\b",
        r"\bliterally\b",
        r"\bhonestly\b",
        r"\bkinda\b",
        r"\bsort of\b",
        r"\bkind of\b",
        r"\bi guess\b",
        r"\bi think\b",
        r"\bprobably\b",
        r"\bmaybe\b",
        r"\banyway\b",
        r"\bso yeah\b",
        r"\bjust\b",
        r"\breally\b",
    ]

    # Technical term patterns
    TECH_PATTERNS = [
        r"\b[A-Z]{2,}[-_]?\d+\b",  # Issue keys like AAP-12345
        r"\b(?:api|sdk|cli|ui|ux|db|sql|json|yaml|xml|html|css|js)\b",
        r"\b(?:kubernetes|k8s|docker|pod|container|namespace)\b",
        r"\b(?:git|branch|commit|merge|pr|mr|pipeline)\b",
        r"\b(?:deploy|release|build|test|debug|fix|bug)\b",
        r"\b(?:endpoint|request|response|auth|token)\b",
        r"\b(?:config|env|var|param|arg)\b",
    ]

    # Greeting patterns
    GREETING_PATTERNS = [
        (r"^hey\b", "hey"),
        (r"^hi\b", "hi"),
        (r"^hello\b", "hello"),
        (r"^yo\b", "yo"),
        (r"^sup\b", "sup"),
        (r"^morning\b", "morning"),
        (r"^good morning\b", "good morning"),
        (r"^afternoon\b", "afternoon"),
        (r"^evening\b", "evening"),
        (r"^hi team\b", "hi team"),
        (r"^hey team\b", "hey team"),
        (r"^hi all\b", "hi all"),
        (r"^hey all\b", "hey all"),
        (r"^hi everyone\b", "hi everyone"),
        (r"^howdy\b", "howdy"),
    ]

    # Signoff patterns
    SIGNOFF_PATTERNS = [
        (r"\bthanks\b[!.]?$", "thanks"),
        (r"\bthank you\b[!.]?$", "thank you"),
        (r"\bcheers\b[!.]?$", "cheers"),
        (r"\blmk\b[!.]?$", "lmk"),
        (r"\blet me know\b[!.]?$", "let me know"),
        (r"\bttyl\b[!.]?$", "ttyl"),
        (r"\btalk soon\b[!.]?$", "talk soon"),
        (r"\bbye\b[!.]?$", "bye"),
        (r"\blater\b[!.]?$", "later"),
        (r"\bpeace\b[!.]?$", "peace"),
        (r"\btake care\b[!.]?$", "take care"),
        (r"\bhave a good one\b[!.]?$", "have a good one"),
        (r"\bsee you\b[!.]?$", "see you"),
        (r"\bregards\b[!.]?$", "regards"),
        (r"\bbest\b[!.]?$", "best"),
    ]

    # Response pattern categories
    ACKNOWLEDGMENT_PATTERNS = [
        "got it",
        "gotcha",
        "understood",
        "makes sense",
        "i see",
        "ah ok",
        "ah okay",
        "oh ok",
        "oh okay",
        "ok got it",
        "roger",
        "copy",
        "noted",
        "ack",
        "k",
        "kk",
    ]

    AGREEMENT_PATTERNS = [
        "sounds good",
        "works for me",
        "lgtm",
        "looks good",
        "yeah",
        "yep",
        "yup",
        "yes",
        "sure",
        "definitely",
        "absolutely",
        "totally",
        "agreed",
        "exactly",
        "right",
        "perfect",
        "great",
        "awesome",
        "nice",
        "cool",
    ]

    DISAGREEMENT_PATTERNS = [
        "hmm",
        "not sure",
        "i don't think",
        "actually",
        "but",
        "however",
        "although",
        "maybe not",
        "i disagree",
        "i'm not convinced",
        "wait",
    ]

    # Emoji regex
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols extended-A
        "\U00002600-\U000026FF"  # misc symbols
        "\U00002700-\U000027BF"  # dingbats
        "]"
    )

    def __init__(self):
        """Initialize the analyzer."""
        pass

    def analyze(self, messages: list[dict]) -> dict[str, Any]:
        """
        Analyze a corpus of messages and extract style patterns.

        Args:
            messages: List of message dicts with 'text' field

        Returns:
            Style profile dictionary
        """
        texts = [msg.get("text", "") for msg in messages if msg.get("text")]

        if not texts:
            return {}

        return {
            "vocabulary": self._analyze_vocabulary(texts),
            "sentence_patterns": self._analyze_sentences(texts),
            "tone": self._analyze_tone(texts),
            "emoji": self._analyze_emoji(texts),
            "greetings": self._analyze_greetings(texts),
            "signoffs": self._analyze_signoffs(texts),
            "response_patterns": self._analyze_response_patterns(texts),
        }

    def _analyze_vocabulary(self, texts: list[str]) -> dict:
        """Analyze vocabulary patterns."""
        all_words = []
        unique_phrases = Counter()
        technical_terms = Counter()
        filler_words = Counter()

        for text in texts:
            # Clean and tokenize
            clean_text = self._clean_text(text)
            words = clean_text.lower().split()

            # Filter stop words for top words
            filtered_words = [w for w in words if w not in self.STOP_WORDS and len(w) > 2]
            all_words.extend(filtered_words)

            # Extract phrases (2-4 word combinations)
            for n in range(2, 5):
                for i in range(len(words) - n + 1):
                    phrase = " ".join(words[i : i + n])
                    if self._is_meaningful_phrase(phrase):
                        unique_phrases[phrase] += 1

            # Extract technical terms
            for pattern in self.TECH_PATTERNS:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    technical_terms[match.lower()] += 1

            # Count filler words
            for pattern in self.FILLER_PATTERNS:
                matches = re.findall(pattern, text, re.IGNORECASE)
                filler_words[pattern.replace(r"\b", "").strip()] += len(matches)

        word_counts = Counter(all_words)

        return {
            "top_words": [w for w, _ in word_counts.most_common(30)],
            "unique_phrases": [p for p, c in unique_phrases.most_common(20) if c >= 2],
            "technical_terms": [t for t, _ in technical_terms.most_common(15)],
            "filler_words": [f for f, c in filler_words.most_common(10) if c >= 2],
            "vocabulary_size": len(set(all_words)),
        }

    def _analyze_sentences(self, texts: list[str]) -> dict:
        """Analyze sentence patterns."""
        lengths = []
        exclamation_count = 0
        question_count = 0
        ellipsis_count = 0
        caps_styles = {"lowercase": 0, "sentence_case": 0, "mixed": 0}

        for text in texts:
            # Clean for analysis
            clean = self._clean_text(text)
            words = clean.split()
            lengths.append(len(words))

            # Punctuation
            if "!" in text:
                exclamation_count += 1
            if "?" in text:
                question_count += 1
            if "..." in text or "…" in text:
                ellipsis_count += 1

            # Capitalization style
            if text == text.lower():
                caps_styles["lowercase"] += 1
            elif text[0].isupper() and text[1:] == text[1:].lower():
                caps_styles["sentence_case"] += 1
            else:
                caps_styles["mixed"] += 1

        total = len(texts) or 1

        # Determine dominant capitalization style
        cap_style = max(caps_styles, key=caps_styles.get)

        return {
            "avg_length": sum(lengths) / len(lengths) if lengths else 0,
            "min_length": min(lengths) if lengths else 0,
            "max_length": max(lengths) if lengths else 0,
            "punctuation": {
                "exclamation_rate": exclamation_count / total,
                "question_rate": question_count / total,
                "ellipsis_rate": ellipsis_count / total,
            },
            "capitalization": cap_style,
        }

    def _analyze_tone(self, texts: list[str]) -> dict:
        """Analyze tone markers."""
        formality_score = 0
        directness_score = 0

        # Formal indicators
        formal_patterns = [
            r"\bplease\b",
            r"\bkindly\b",
            r"\bwould you\b",
            r"\bcould you\b",
            r"\bi would\b",
            r"\bthank you\b",
            r"\bregards\b",
            r"\bsincerely\b",
        ]

        # Informal indicators
        informal_patterns = [
            r"\bhey\b",
            r"\byo\b",
            r"\bsup\b",
            r"\byeah\b",
            r"\byep\b",
            r"\bnope\b",
            r"\bgonna\b",
            r"\bwanna\b",
            r"\bgotta\b",
            r"\blol\b",
            r"\bhaha\b",
            r"\bomg\b",
            r"\bbtw\b",
        ]

        # Direct indicators
        direct_patterns = [
            r"^(?:do|please|can you|could you|would you)",
            r"\bneed\b",
            r"\bmust\b",
            r"\bshould\b",
        ]

        # Indirect indicators
        indirect_patterns = [
            r"\bmaybe\b",
            r"\bperhaps\b",
            r"\bi think\b",
            r"\bi believe\b",
            r"\bit seems\b",
            r"\bpossibly\b",
            r"\bmight\b",
        ]

        formal_count = 0
        informal_count = 0
        direct_count = 0
        indirect_count = 0

        for text in texts:
            text_lower = text.lower()

            for pattern in formal_patterns:
                if re.search(pattern, text_lower):
                    formal_count += 1
                    break

            for pattern in informal_patterns:
                if re.search(pattern, text_lower):
                    informal_count += 1
                    break

            for pattern in direct_patterns:
                if re.search(pattern, text_lower):
                    direct_count += 1
                    break

            for pattern in indirect_patterns:
                if re.search(pattern, text_lower):
                    indirect_count += 1
                    break

        # Calculate scores (0 = casual/indirect, 1 = formal/direct)
        if formal_count + informal_count > 0:
            formality_score = formal_count / (formal_count + informal_count)
        else:
            formality_score = 0.5

        if direct_count + indirect_count > 0:
            directness_score = direct_count / (direct_count + indirect_count)
        else:
            directness_score = 0.5

        return {
            "formality": formality_score,
            "directness": directness_score,
            "formal_indicators": formal_count,
            "informal_indicators": informal_count,
        }

    def _analyze_emoji(self, texts: list[str]) -> dict:
        """Analyze emoji usage patterns."""
        emoji_counter = Counter()
        messages_with_emoji = 0

        # Contextual emoji tracking
        agreement_emojis = Counter()
        thinking_emojis = Counter()
        positive_emojis = Counter()

        for text in texts:
            emojis = self.EMOJI_PATTERN.findall(text)
            if emojis:
                messages_with_emoji += 1
                emoji_counter.update(emojis)

                # Categorize by context
                text_lower = text.lower()
                for emoji in emojis:
                    if any(p in text_lower for p in ["yes", "agree", "good", "ok", "sure"]):
                        agreement_emojis[emoji] += 1
                    if any(p in text_lower for p in ["think", "hmm", "wonder", "maybe"]):
                        thinking_emojis[emoji] += 1
                    if any(p in text_lower for p in ["great", "awesome", "nice", "love", "thanks"]):
                        positive_emojis[emoji] += 1

        total = len(texts) or 1

        return {
            "frequency": messages_with_emoji / total,
            "favorites": [e for e, _ in emoji_counter.most_common(10)],
            "total_emoji_count": sum(emoji_counter.values()),
            "unique_emojis": len(emoji_counter),
            "contextual_patterns": {
                "agreement": [e for e, _ in agreement_emojis.most_common(3)],
                "thinking": [e for e, _ in thinking_emojis.most_common(3)],
                "positive": [e for e, _ in positive_emojis.most_common(3)],
            },
        }

    def _analyze_greetings(self, texts: list[str]) -> dict:
        """Analyze greeting patterns."""
        greeting_counter = Counter()

        for text in texts:
            text_lower = text.lower().strip()
            for pattern, greeting in self.GREETING_PATTERNS:
                if re.match(pattern, text_lower):
                    greeting_counter[greeting] += 1
                    break

        return {
            "common": [g for g, _ in greeting_counter.most_common(10)],
            "total_greetings": sum(greeting_counter.values()),
        }

    def _analyze_signoffs(self, texts: list[str]) -> dict:
        """Analyze signoff patterns."""
        signoff_counter = Counter()

        for text in texts:
            text_lower = text.lower().strip()
            for pattern, signoff in self.SIGNOFF_PATTERNS:
                if re.search(pattern, text_lower):
                    signoff_counter[signoff] += 1
                    break

        return {
            "common": [s for s, _ in signoff_counter.most_common(10)],
            "total_signoffs": sum(signoff_counter.values()),
        }

    def _analyze_response_patterns(self, texts: list[str]) -> dict:
        """Analyze response patterns (acknowledgment, agreement, disagreement)."""
        ack_counter = Counter()
        agree_counter = Counter()
        disagree_counter = Counter()

        for text in texts:
            text_lower = text.lower().strip()

            # Check acknowledgments
            for pattern in self.ACKNOWLEDGMENT_PATTERNS:
                if pattern in text_lower:
                    ack_counter[pattern] += 1

            # Check agreements
            for pattern in self.AGREEMENT_PATTERNS:
                if pattern in text_lower:
                    agree_counter[pattern] += 1

            # Check disagreements
            for pattern in self.DISAGREEMENT_PATTERNS:
                if pattern in text_lower:
                    disagree_counter[pattern] += 1

        return {
            "acknowledgment": [a for a, _ in ack_counter.most_common(10)],
            "agreement": [a for a, _ in agree_counter.most_common(10)],
            "disagreement": [d for d, _ in disagree_counter.most_common(10)],
        }

    def _clean_text(self, text: str) -> str:
        """Clean text for analysis."""
        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)
        # Remove mentions
        text = re.sub(r"<@\w+>", "", text)
        # Remove channel references
        text = re.sub(r"<#\w+\|[^>]+>", "", text)
        # Remove special Slack formatting
        text = re.sub(r"<[^>]+>", "", text)
        # Remove emojis for word analysis
        text = self.EMOJI_PATTERN.sub("", text)
        # Remove extra whitespace
        text = " ".join(text.split())
        return text

    def _is_meaningful_phrase(self, phrase: str) -> bool:
        """Check if a phrase is meaningful (not just stop words)."""
        words = phrase.split()
        # At least one non-stop word
        non_stop = [w for w in words if w not in self.STOP_WORDS]
        return len(non_stop) >= 1 and len(phrase) >= 5

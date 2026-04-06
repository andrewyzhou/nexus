import os
import re
from google import genai
from sklearn.feature_extraction.text import TfidfVectorizer

class NewsSummarizer:
    def __init__(self, api_key=None):
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = None

    def extract_keywords(self, text, top_n=5):
        """Extract keywords using TF-IDF."""
        if not text or len(text.strip()) == 0:
            return []
            
        # Basic text cleaning
        text = re.sub(r'[^a-zA-Z\s]', '', text).lower()
        
        try:
            vectorizer = TfidfVectorizer(stop_words='english')
            tfidf_matrix = vectorizer.fit_transform([text])
            feature_names = vectorizer.get_feature_names_out()
            dense = tfidf_matrix.todense()
            episode = dense[0].tolist()[0]
            phrase_scores = [pair for pair in zip(range(0, len(episode)), episode) if pair[1] > 0]
            sorted_phrase_scores = sorted(phrase_scores, key=lambda t: t[1] * -1)
            
            keywords = []
            for phrase, score in [(feature_names[word_id], score) for (word_id, score) in sorted_phrase_scores][:top_n]:
                keywords.append(phrase)
            return keywords
        except ValueError:
            # Vocabulary is empty or other exception
            return []

    def extract_context(self, text, keywords):
        """Extract sentences containing keywords to form a context block."""
        if not text:
            return ""
            
        sentences = re.split(r'(?<=[.!?]) +', text)
        context_sentences = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(kw in sentence_lower for kw in keywords):
                context_sentences.append(sentence.strip())
                
        # Return at most 10 relevant sentences to keep prompt concise
        return " ".join(context_sentences[:10])

    def generate_summary(self, context, label):
        """Use Gemini to create a two-sentence summary."""
        if not self.client:
            return "Mock sentence 1. Mock sentence 2."
            
        if not context:
            return "No relevant news context found. Unable to generate summary."
            
        prompt = (
            f"You are a financial analyst. Read the following recent news context for '{label}'. "
            f"Write exactly two sentences summarizing this news. Do not use conversational filler.\n\n"
            f"Context:\n{context}"
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            summary = response.text.strip()
            # Clean up newlines if any
            summary = summary.replace('\n', ' ')
            return summary
        except Exception as e:
            print(f"Error generating summary: {e}")
            return "Error generating summary. Please check API key."

if __name__ == "__main__":
    summarizer = NewsSummarizer()
    sample_text = "Apple Inc. today announced new iPhone models with advanced AI capabilities. The new chips are expected to boost sales in Q4. However, some analysts worry about pricing out consumers."
    keywords = summarizer.extract_keywords(sample_text)
    print("Keywords:", keywords)
    context = summarizer.extract_context(sample_text, keywords)
    print("Context:", context)
    # mock summary since API key might not be set
    print("Summary:", summarizer.generate_summary(context, "AAPL"))

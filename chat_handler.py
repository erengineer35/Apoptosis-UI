#!/usr/bin/env python3
"""
AI Chat Handler for ApoptosisUI
Uses Groq API (free tier: 14,400 requests/day) with Llama 3.1 8B
Includes conversation memory and analysis context awareness.

Authors: Atalay ŞAHAN & Gülce Nur Evren
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Get script directory first
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables from script directory
try:
    from dotenv import load_dotenv
    env_path = SCRIPT_DIR / ".env"
    load_dotenv(env_path)
except ImportError:
    pass  # dotenv not required if env vars set directly

# Groq client
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    print("Warning: groq package not installed. Run: pip install groq", file=sys.stderr)

# Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
CHAT_HISTORY_FILE = SCRIPT_DIR / "chat_history.json"
MAX_HISTORY_MESSAGES = 20  # Keep last N messages for context

# System prompts
SYSTEM_PROMPT_CHAT = """You are an AI assistant for a Cell Morphology Analysis application (ApoptosisUI).
You help researchers and scientists understand their apoptosis detection results.

Your capabilities:
- Explain cell analysis results in clear, scientific language
- Interpret statistics like cell counts, areas, and distributions
- Provide context about what different metrics mean
- Answer questions about the analysis methodology
- Help users understand the significance of their findings

Guidelines:
- Be concise but thorough
- Use scientific terminology appropriately
- If data is not available, explain what you would need
- Always be helpful and educational

Current Analysis Context:
{context}
"""

SYSTEM_PROMPT_REPORT = """You are a medical/scientific report writer for cell morphology analysis.
Generate a professional interpretation section for an analysis report.

Based on the provided data, write 2-3 paragraphs covering:
1. Overall assessment of cell health and population distribution
2. Significance of the affected/apoptotic cell ratio
3. Notable observations about cell morphology and size distribution
4. Brief conclusion or recommendations if applicable

Style guidelines:
- Professional, scientific tone
- Objective and data-driven
- Avoid speculation beyond what the data shows
- Use proper medical/scientific terminology

Analysis Data:
{data}

Write the interpretation now:"""


class ChatMemory:
    """Simple JSON-based conversation memory."""

    def __init__(self, file_path: Path = CHAT_HISTORY_FILE):
        self.file_path = file_path
        self.messages: List[Dict[str, str]] = []
        self.load()

    def load(self):
        """Load chat history from file."""
        try:
            if self.file_path.exists():
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.messages = data.get('messages', [])[-MAX_HISTORY_MESSAGES:]
        except Exception:
            self.messages = []

    def save(self):
        """Save chat history to file."""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'messages': self.messages[-MAX_HISTORY_MESSAGES:],
                    'last_updated': datetime.now().isoformat()
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save chat history: {e}", file=sys.stderr)

    def add_message(self, role: str, content: str):
        """Add a message to history."""
        self.messages.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        # Keep only last N messages
        if len(self.messages) > MAX_HISTORY_MESSAGES:
            self.messages = self.messages[-MAX_HISTORY_MESSAGES:]
        self.save()

    def get_messages_for_api(self) -> List[Dict[str, str]]:
        """Get messages formatted for API call."""
        return [{'role': m['role'], 'content': m['content']} for m in self.messages]

    def clear(self):
        """Clear chat history."""
        self.messages = []
        self.save()


class AnalysisContext:
    """Manages the current analysis context for AI conversations."""

    def __init__(self):
        self.data: Optional[Dict[str, Any]] = None
        self.load_latest()

    def load_latest(self):
        """Load the latest analysis results."""
        results_path = SCRIPT_DIR / "results.json"
        try:
            if results_path.exists():
                with open(results_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
        except Exception:
            self.data = None

    def get_context_string(self) -> str:
        """Get formatted context string for prompts."""
        if not self.data:
            return "No analysis data available. Please run an analysis first."

        stats = self.data.get('statistics', {})
        class_dist = stats.get('class_distribution', {})
        area_stats = stats.get('area_stats', {})
        cell_counts = stats.get('cell_counts_by_class', {})

        context = f"""
Analysis File: {self.data.get('input_file', 'Unknown')}
Timestamp: {self.data.get('timestamp', 'Unknown')}

Cell Counts:
- Total Cells: {stats.get('total_cells', 'N/A')}
- Healthy: {cell_counts.get('healthy', 'N/A')}
- Affected: {cell_counts.get('affected', 'N/A')}
- Irrelevant: {cell_counts.get('irrelevant', 'N/A')}

Class Distribution (pixels):
- Background: {class_dist.get('background', {}).get('percent', 'N/A')}%
- Healthy: {class_dist.get('healthy', {}).get('percent', 'N/A')}%
- Affected: {class_dist.get('affected', {}).get('percent', 'N/A')}%
- Irrelevant: {class_dist.get('irrelevant', {}).get('percent', 'N/A')}%

Cell Area Statistics:
- Mean Area: {area_stats.get('mean', 'N/A')} px²
- Median Area: {area_stats.get('median', 'N/A')} px²
- Std Deviation: {area_stats.get('std', 'N/A')} px²
- CV%: {area_stats.get('cv_percent', 'N/A')}%
- Min Area: {area_stats.get('min', 'N/A')} px²
- Max Area: {area_stats.get('max', 'N/A')} px²
"""
        return context

    def get_data_for_report(self) -> Dict[str, Any]:
        """Get data formatted for report generation."""
        if not self.data:
            return {}

        stats = self.data.get('statistics', {})
        cell_counts = stats.get('cell_counts_by_class', {})
        total = stats.get('total_cells', 0)

        return {
            'total_cells': total,
            'healthy': cell_counts.get('healthy', 0),
            'healthy_pct': round(cell_counts.get('healthy', 0) / max(total, 1) * 100, 1),
            'affected': cell_counts.get('affected', 0),
            'affected_pct': round(cell_counts.get('affected', 0) / max(total, 1) * 100, 1),
            'irrelevant': cell_counts.get('irrelevant', 0),
            'irrelevant_pct': round(cell_counts.get('irrelevant', 0) / max(total, 1) * 100, 1),
            'mean_area': stats.get('area_stats', {}).get('mean', 0),
            'median_area': stats.get('area_stats', {}).get('median', 0),
            'std_area': stats.get('area_stats', {}).get('std', 0),
            'cv_percent': stats.get('area_stats', {}).get('cv_percent', 0),
            'class_distribution': stats.get('class_distribution', {}),
        }


class ChatHandler:
    """Main chat handler with Groq API integration."""

    def __init__(self):
        self.memory = ChatMemory()
        self.context = AnalysisContext()
        self.client = None

        if GROQ_AVAILABLE and GROQ_API_KEY:
            try:
                self.client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                print(f"Warning: Could not initialize Groq client: {e}", file=sys.stderr)

    def is_available(self) -> bool:
        """Check if chat functionality is available."""
        return self.client is not None

    def refresh_context(self):
        """Reload the analysis context."""
        self.context.load_latest()

    def chat(self, user_message: str) -> str:
        """Send a message and get a response."""
        if not self.is_available():
            return "Error: AI chat is not available. Please check your API key configuration."

        # Refresh context in case new analysis was run
        self.refresh_context()

        # Add user message to history
        self.memory.add_message('user', user_message)

        try:
            # Build messages for API
            system_message = SYSTEM_PROMPT_CHAT.format(context=self.context.get_context_string())

            messages = [{'role': 'system', 'content': system_message}]
            messages.extend(self.memory.get_messages_for_api())

            # Call Groq API
            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
            )

            assistant_message = response.choices[0].message.content

            # Add assistant response to history
            self.memory.add_message('assistant', assistant_message)

            return assistant_message

        except Exception as e:
            error_msg = f"Error communicating with AI: {str(e)}"
            print(error_msg, file=sys.stderr)
            return error_msg

    def generate_report_interpretation(self) -> str:
        """Generate AI interpretation for the report."""
        if not self.is_available():
            return "AI interpretation not available. Please configure your API key."

        self.refresh_context()
        data = self.context.get_data_for_report()

        if not data:
            return "No analysis data available for interpretation."

        try:
            # Format data for prompt
            data_str = json.dumps(data, indent=2)
            prompt = SYSTEM_PROMPT_REPORT.format(data=data_str)

            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.5,  # Lower temperature for more consistent reports
                max_tokens=1024,
            )

            return response.choices[0].message.content

        except Exception as e:
            return f"Error generating interpretation: {str(e)}"

    def get_quick_summary(self) -> str:
        """Get a quick one-line summary of the current analysis."""
        if not self.is_available():
            return "AI not available"

        self.refresh_context()

        if not self.context.data:
            return "No analysis data available"

        try:
            prompt = f"""Based on this data, provide a ONE sentence summary (max 20 words):
{self.context.get_context_string()}

Summary:"""

            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3,
                max_tokens=100,
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            return f"Error: {str(e)}"

    def clear_history(self):
        """Clear conversation history."""
        self.memory.clear()

    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history."""
        return self.memory.messages.copy()


# CLI interface for testing
def main():
    """Interactive CLI for testing the chat handler."""
    print("=" * 60)
    print("ApoptosisUI AI Chat - Test Interface")
    print("=" * 60)

    if not GROQ_API_KEY:
        print("Error: GROQ_API_KEY not set in environment or .env file")
        return

    handler = ChatHandler()

    if not handler.is_available():
        print("Error: Chat handler not available")
        return

    print(f"Model: {GROQ_MODEL}")
    print("Type 'quit' to exit, 'clear' to clear history, 'report' for interpretation")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if not user_input:
                continue

            if user_input.lower() == 'quit':
                break
            elif user_input.lower() == 'clear':
                handler.clear_history()
                print("Chat history cleared.")
                continue
            elif user_input.lower() == 'report':
                print("\nGenerating report interpretation...")
                interpretation = handler.generate_report_interpretation()
                print(f"\nAI Report:\n{interpretation}")
                continue
            elif user_input.lower() == 'summary':
                summary = handler.get_quick_summary()
                print(f"\nSummary: {summary}")
                continue

            response = handler.chat(user_input)
            print(f"\nAI: {response}")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()

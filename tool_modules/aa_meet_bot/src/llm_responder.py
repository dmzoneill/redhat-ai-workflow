"""
LLM Response Generator.

Handles:
- Processing wake-word triggered commands
- Generating contextual responses using Ollama (iGPU)
- Jira context integration
"""

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)

# Ollama configuration
OLLAMA_HOST = "http://localhost:11434"  # Default Ollama port
OLLAMA_MODEL = "qwen2.5:0.5b"  # Fast model for real-time responses (upgrade to 7b for better quality)


@dataclass
class JiraContext:
    """Context from Jira for the current sprint."""
    sprint_name: str = ""
    sprint_goal: str = ""
    issues: List[dict] = field(default_factory=list)
    my_issues: List[dict] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    
    def to_prompt_context(self) -> str:
        """Convert to a string for LLM context."""
        if not self.issues:
            return "No Jira context loaded."
        
        lines = [
            f"## Current Sprint: {self.sprint_name}",
            f"Sprint Goal: {self.sprint_goal}",
            "",
            "### My Issues:",
        ]
        
        for issue in self.my_issues[:5]:  # Limit to 5 issues
            status = issue.get("status", "Unknown")
            summary = issue.get("summary", "")[:60]
            key = issue.get("key", "")
            lines.append(f"- [{key}] {summary} ({status})")
        
        lines.append("")
        lines.append("### Team Issues:")
        
        for issue in self.issues[:10]:  # Limit to 10 issues
            if issue not in self.my_issues:
                status = issue.get("status", "Unknown")
                summary = issue.get("summary", "")[:60]
                key = issue.get("key", "")
                assignee = issue.get("assignee", "Unassigned")
                lines.append(f"- [{key}] {summary} ({status}) - {assignee}")
        
        return "\n".join(lines)


@dataclass
class LLMResponse:
    """Response from the LLM."""
    text: str
    confidence: float = 1.0
    action: Optional[str] = None  # "update_jira", "lookup", "respond", etc.
    action_params: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None


class LLMResponder:
    """
    LLM-based response generator for meeting interactions.
    
    Uses Ollama with qwen2.5:7b on iGPU for fast inference.
    """
    
    def __init__(self):
        self.config = get_config()
        self.jira_context = JiraContext()
        self.conversation_history: List[dict] = []
        self.max_history = 10
        
        # System prompt for meeting assistant
        self.system_prompt = """You are David's AI assistant in a work meeting. You respond to questions and provide status updates.

IMPORTANT RULES:
1. Keep responses SHORT (1-3 sentences max) - this is a verbal meeting
2. Be conversational and natural - you're speaking, not writing
3. Focus on Jira/project status when asked
4. Never respond with code or technical details unless specifically asked
5. If you don't know something, say so briefly

You have access to the current sprint's Jira context. Use it to answer questions about:
- Issue status
- Sprint progress
- Blockers
- Assignments

Example responses:
- "The API refactoring is in progress, about 70% done. Should be ready for review tomorrow."
- "I'm currently working on AAP-12345, the authentication fix. No blockers."
- "The sprint is on track. We have 3 items in review and 2 in progress."
"""
    
    async def initialize(self) -> bool:
        """Check Ollama is available."""
        try:
            result = subprocess.run(
                ["curl", "-s", f"{OLLAMA_HOST}/api/tags"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                models = [m["name"] for m in data.get("models", [])]
                
                if OLLAMA_MODEL in models or any(OLLAMA_MODEL.split(":")[0] in m for m in models):
                    logger.info(f"Ollama ready with model {OLLAMA_MODEL}")
                    return True
                else:
                    logger.warning(f"Model {OLLAMA_MODEL} not found. Available: {models}")
                    logger.info(f"Run: ollama pull {OLLAMA_MODEL}")
                    return False
            else:
                logger.error("Ollama not responding")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            return False
    
    async def load_jira_context(self, project: str = "AAP") -> bool:
        """
        Load Jira context for the current sprint.
        
        This preloads sprint information so responses are fast.
        """
        try:
            # Use the existing Jira MCP tools
            # For now, we'll create a placeholder that can be filled by the MCP tools
            logger.info(f"Loading Jira context for project {project}...")
            
            # This would normally call jira_my_issues and jira_search
            # For now, set up the structure
            self.jira_context = JiraContext(
                sprint_name="Current Sprint",
                sprint_goal="Deliver key features",
                issues=[],
                my_issues=[],
                last_updated=datetime.now()
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load Jira context: {e}")
            return False
    
    def update_jira_context(self, issues: List[dict], my_issues: List[dict] = None):
        """Update Jira context with fresh data."""
        self.jira_context.issues = issues
        self.jira_context.my_issues = my_issues or []
        self.jira_context.last_updated = datetime.now()
    
    async def generate_response(
        self,
        command: str,
        speaker: str = "Someone",
        context_before: List[str] = None,
    ) -> LLMResponse:
        """
        Generate a response to a command/question.
        
        Args:
            command: The text after the wake word
            speaker: Who said it
            context_before: Recent conversation context
            
        Returns:
            LLMResponse with the generated text
        """
        try:
            # Build the prompt
            messages = [
                {"role": "system", "content": self.system_prompt},
            ]
            
            # Add Jira context
            jira_ctx = self.jira_context.to_prompt_context()
            if jira_ctx:
                messages.append({
                    "role": "system",
                    "content": f"Current Jira Context:\n{jira_ctx}"
                })
            
            # Add conversation history
            for msg in self.conversation_history[-self.max_history:]:
                messages.append(msg)
            
            # Add context from meeting
            if context_before:
                context_text = "\n".join(context_before[-5:])
                messages.append({
                    "role": "system",
                    "content": f"Recent meeting conversation:\n{context_text}"
                })
            
            # Add the current command
            messages.append({
                "role": "user",
                "content": f"{speaker} asked: {command}"
            })
            
            # Call Ollama
            response_text = await self._call_ollama(messages)
            
            if response_text:
                # Add to history
                self.conversation_history.append({
                    "role": "user",
                    "content": f"{speaker}: {command}"
                })
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                # Trim history
                if len(self.conversation_history) > self.max_history * 2:
                    self.conversation_history = self.conversation_history[-self.max_history * 2:]
                
                return LLMResponse(
                    text=response_text,
                    success=True
                )
            else:
                return LLMResponse(
                    text="",
                    success=False,
                    error="No response from LLM"
                )
                
        except Exception as e:
            logger.error(f"LLM response failed: {e}")
            return LLMResponse(
                text="",
                success=False,
                error=str(e)
            )
    
    async def _call_ollama(self, messages: List[dict]) -> Optional[str]:
        """Call Ollama API."""
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 100,  # Keep responses short
                }
            }
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["curl", "-s", "-X", "POST",
                     f"{OLLAMA_HOST}/api/chat",
                     "-H", "Content-Type: application/json",
                     "-d", json.dumps(payload)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("message", {}).get("content", "")
            else:
                logger.error(f"Ollama call failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("Ollama timed out")
            return None
        except Exception as e:
            logger.error(f"Ollama call error: {e}")
            return None
    
    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []


# Global instance
_llm_responder: Optional[LLMResponder] = None


def get_llm_responder() -> LLMResponder:
    """Get or create the global LLM responder instance."""
    global _llm_responder
    if _llm_responder is None:
        _llm_responder = LLMResponder()
    return _llm_responder


async def generate_meeting_response(
    command: str,
    speaker: str = "Someone",
    context: List[str] = None
) -> LLMResponse:
    """
    Convenience function to generate a meeting response.
    
    Args:
        command: The command/question after wake word
        speaker: Who asked
        context: Recent conversation
        
    Returns:
        LLMResponse with generated text
    """
    responder = get_llm_responder()
    return await responder.generate_response(command, speaker, context)



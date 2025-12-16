"""
Explainer for generating human-readable explanations of bot decisions.
Does NOT make trading decisions - only explains them.
"""
from typing import Dict, Optional
import logging

from ai.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class Explainer:
    """
    Generate explanations for bot decisions using OpenAI.
    
    STRICTLY for explanations only - never for trading decisions.
    """
    
    def __init__(self, openai_client: OpenAIClient):
        self.client = openai_client
    
    def explain_decision(
        self,
        decision: str,
        context: Dict
    ) -> str:
        """
        Generate explanation for a bot decision.
        
        Args:
            decision: Decision type (e.g., 'buy', 'sell', 'hold', 'pause')
            context: Context dictionary with relevant metrics
        
        Returns:
            Human-readable explanation string
        """
        if not self.client.is_enabled():
            return self._fallback_explanation(decision, context)
        
        # Construct prompt
        system_prompt = """You are a trading bot explainer. 
Your job is to explain trading decisions in simple terms.

You MUST NOT:
- Make trading decisions
- Suggest buying or selling
- Override any decisions
- Change any parameters

ONLY explain the decision that was already made by the quantitative system."""

        user_prompt = f"""Explain this trading bot decision in 2-3 sentences:

Decision: {decision}
Context: {context}

Keep it simple and factual."""

        # Call API
        response = self.client.call_api(
            prompt=user_prompt,
            system_prompt=system_prompt,
            use_cache=False  # Don't cache explanations
        )
        
        if not response:
            return self._fallback_explanation(decision, context)
        
        explanation = response.get('content', '')
        return explanation if explanation else self._fallback_explanation(decision, context)
    
    def _fallback_explanation(self, decision: str, context: Dict) -> str:
        """Generate simple fallback explanation without LLM."""
        if decision == 'buy':
            return f"Buy signal generated based on momentum and risk checks."
        elif decision == 'sell':
            return f"Sell signal due to exit conditions."
        elif decision == 'hold':
            return f"No action - waiting for better conditions."
        elif decision == 'pause':
            reason = context.get('reason', 'risk controls')
            return f"Trading paused due to {reason}."
        else:
            return f"Decision: {decision}"
    
    def explain_news_impact(
        self,
        symbol: str,
        news_summary: Dict,
        action: str
    ) -> str:
        """
        Explain how news impacts trading decision.
        
        Args:
            symbol: Trading pair
            news_summary: Summary of news metrics
            action: Action taken (pause, reduce, continue)
        
        Returns:
            Explanation string
        """
        if not self.client.is_enabled():
            return f"News analysis for {symbol}: Action = {action}"
        
        system_prompt = """You are a trading bot explainer.
Explain how news affects trading in 2-3 sentences.

You MUST NOT make trading decisions or suggest actions.
Only explain what the bot decided to do."""

        user_prompt = f"""Explain this news impact:

Symbol: {symbol}
News Summary: {news_summary}
Bot Action: {action}

Explain in simple terms."""

        response = self.client.call_api(
            prompt=user_prompt,
            system_prompt=system_prompt,
            use_cache=False
        )
        
        if not response:
            return f"News analysis for {symbol}: Action = {action}"
        
        return response.get('content', f"News analysis for {symbol}: Action = {action}")
    
    def explain_risk_metrics(
        self,
        symbol: str,
        risk_metrics: Dict
    ) -> str:
        """
        Explain risk metrics in simple terms.
        
        Args:
            symbol: Trading pair
            risk_metrics: Risk metrics dictionary
        
        Returns:
            Explanation string
        """
        if not self.client.is_enabled():
            return f"Risk metrics for {symbol}"
        
        system_prompt = """You are a trading bot explainer.
Explain risk metrics in 2-3 sentences for a non-technical user.

You MUST NOT suggest actions or make decisions."""

        user_prompt = f"""Explain these risk metrics:

Symbol: {symbol}
Risk Metrics: {risk_metrics}

Simple explanation please."""

        response = self.client.call_api(
            prompt=user_prompt,
            system_prompt=system_prompt,
            use_cache=True
        )
        
        if not response:
            return f"Risk metrics for {symbol}"
        
        return response.get('content', f"Risk metrics for {symbol}")

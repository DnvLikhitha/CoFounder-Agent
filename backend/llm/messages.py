"""Assemble the system and agent text into chat messages."""


def chat_messages(system_prompt, agent_prompt):
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": agent_prompt}]

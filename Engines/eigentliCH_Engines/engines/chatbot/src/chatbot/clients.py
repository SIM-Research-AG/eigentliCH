"""Upstream callers. ``chatbot`` calls no other engine.

It is stateless with respect to client data: the caller (the consumer app) sends, with each question,
the approved knowledge notes and the client facts the answer may use, so there is nothing upstream to
fetch. The one service it calls is the model, and that client is ``spark7.py``.
"""

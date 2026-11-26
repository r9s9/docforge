"""DocForge evaluation suite.

Measures DocForge's pipelines from the outside: it builds a synthetic corpus, calls the real
service functions in an isolated sandbox, and turns what they return into metrics. Nothing in
this package is imported by the app, and the app's code is never changed. See DESIGN.md.
"""

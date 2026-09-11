"""Single authoritative source of the running release identity.

The UI, the health endpoint, export manifests and the packaging metadata all read
these values; nothing else may type a version number by hand.
"""

__version__ = "1.0.1"
TOOL_ID = "online-annotator"
TOOL_NAME = "Online Annotator"

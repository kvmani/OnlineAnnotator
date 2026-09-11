#!/usr/bin/env python3
"""Convenience entry point for OnlineAnnotator server."""

import os
import sys
import uvicorn
from backend.app.config import get_config

if __name__ == "__main__":
    config = get_config()
    host = os.getenv("ONLINE_ANNOTATOR_HOST", config.server.host)
    port = int(os.getenv("ONLINE_ANNOTATOR_PORT", config.server.port))

    print(f"================================================================")
    print(f"  OnlineAnnotator - Microstructure Semantic Segmentation Server")
    print(f"  Target Application: HydrideSegmentation & Material Workflows")
    print(f"  Listening at: http://{host}:{port}")
    print(f"================================================================")

    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )

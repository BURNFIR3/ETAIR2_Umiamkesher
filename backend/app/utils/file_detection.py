"""File family detection based on mime type and file extension."""

EXTENSION_FAMILY_MAP = {
    # Text / Office
    "pdf": "text_office",
    "docx": "text_office",
    "doc": "text_office",
    "pptx": "text_office",
    "ppt": "text_office",
    "txt": "text_office",
    "md": "text_office",
    "html": "text_office",
    "htm": "text_office",
    # Tables / Structured
    "csv": "table",
    "tsv": "table",
    "xlsx": "table",
    "xls": "table",
    "ods": "table",
    # Images / Scans
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "tiff": "image",
    "tif": "image",
    "bmp": "image",
    "gif": "image",
    # Audio
    "mp3": "audio",
    "wav": "audio",
    "m4a": "audio",
    "aac": "audio",
    "ogg": "audio",
    # CAD / Engineering
    "dwg": "cad",
    "dxf": "cad",
    "dgn": "cad",
    "step": "cad",
    "stp": "cad",
    "iges": "cad",
    "igs": "cad",
    "stl": "cad",
    "ifc": "cad",
    # Operational / Exports
    "json": "operational",
    "xml": "operational",
    "log": "operational",
}

MIME_FAMILY_MAP = {
    "application/pdf": "text_office",
    "application/msword": "text_office",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "text_office",
    "application/vnd.ms-powerpoint": "text_office",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "text_office",
    "text/plain": "text_office",
    "text/html": "text_office",
    "text/csv": "table",
    "application/vnd.ms-excel": "table",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "table",
    "image/jpeg": "image",
    "image/png": "image",
    "image/tiff": "image",
    "image/bmp": "image",
    "image/gif": "image",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/mp4": "audio",
    "audio/aac": "audio",
    "application/json": "operational",
    "application/xml": "operational",
    "text/xml": "operational",
}


def detect_file_family(filename: str, mime_type: str) -> str:
    """Detect file family from extension first, fallback to MIME type."""
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in EXTENSION_FAMILY_MAP:
            return EXTENSION_FAMILY_MAP[ext]

    if mime_type in MIME_FAMILY_MAP:
        return MIME_FAMILY_MAP[mime_type]

    return "unknown"

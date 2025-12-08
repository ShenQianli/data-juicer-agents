# -*- coding: utf-8 -*-
import os
import os.path as osp
import json
import logging
import hashlib
import time
from typing import Optional

from langchain_community.vectorstores import FAISS

VECTOR_INDEX_CACHE_PATH = osp.join(osp.dirname(__file__), "vector_index_cache")

# Global variable to cache the vector store
_cached_vector_store: Optional[FAISS] = None
_cached_tools_info: Optional[list] = None
_cached_content_hash: Optional[str] = None

# Global variable for agent lifecycle management
_global_dj_func_info: Optional[list] = None


def fast_text_encoder(text: str) -> str:
    """Fast encoding using xxHash algorithm"""
    import xxhash

    hasher = xxhash.xxh64(seed=0)
    hasher.update(text.encode("utf-8"))

    # Return 16-character hexadecimal string (64-bit)
    return hasher.hexdigest()


def _get_content_hash(dj_func_info: list) -> str:
    """Get content hash of dj_func_info using SHA256"""
    try:
        # Convert to JSON string with sorted keys for consistent hashing
        content_str = json.dumps(dj_func_info, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content_str.encode("utf-8")).hexdigest()
    except Exception as e:
        logging.warning(f"Failed to compute content hash: {e}")
        return ""


def _load_cached_index() -> bool:
    """Load cached vector index from disk"""
    global _cached_vector_store, _cached_tools_info, _cached_content_hash

    try:
        # Get current dj_func_info
        dj_func_info = get_dj_func_info()
        current_hash = _get_content_hash(dj_func_info)

        if not current_hash:
            return False

        # Ensure cache directory exists
        os.makedirs(VECTOR_INDEX_CACHE_PATH, exist_ok=True)

        index_path = osp.join(VECTOR_INDEX_CACHE_PATH, "faiss_index")
        metadata_path = osp.join(VECTOR_INDEX_CACHE_PATH, "metadata.json")

        if not all(os.path.exists(p) for p in [index_path, metadata_path]):
            return False

        # Check if cached index matches current tools info content
        with open(metadata_path, "r") as f:
            metadata = json.load(f)

        cached_hash = metadata.get("content_hash", "")

        if current_hash != cached_hash:
            logging.info("Content hash mismatch, need to rebuild index")
            return False

        # Load cached data
        from langchain_community.embeddings import DashScopeEmbeddings

        embeddings = DashScopeEmbeddings(
            dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="text-embedding-v1",
        )

        _cached_vector_store = FAISS.load_local(
            index_path,
            embeddings,
            allow_dangerous_deserialization=True,
        )

        _cached_tools_info = dj_func_info
        _cached_content_hash = cached_hash

        logging.info("Successfully loaded cached vector index")
        return True

    except Exception as e:
        logging.warning(f"Failed to load cached index: {e}")
        return False


def _save_cached_index():
    """Save vector index to disk cache"""
    global _cached_vector_store, _cached_content_hash

    try:
        # Ensure cache directory exists
        os.makedirs(VECTOR_INDEX_CACHE_PATH, exist_ok=True)

        index_path = osp.join(VECTOR_INDEX_CACHE_PATH, "faiss_index")
        metadata_path = osp.join(VECTOR_INDEX_CACHE_PATH, "metadata.json")

        # Save vector store
        if _cached_vector_store:
            _cached_vector_store.save_local(index_path)

        # Save metadata
        metadata = {
            "content_hash": _cached_content_hash,
            "created_at": time.time(),
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        logging.info("Successfully saved vector index to cache")

    except Exception as e:
        logging.error(f"Failed to save cached index: {e}")


def init_dj_func_info():
    """Initialize dj_func_info at agent startup"""
    global _global_dj_func_info

    try:
        logging.info("Initializing dj_func_info for agent lifecycle...")
        from .create_dj_func_info import dj_func_info

        _global_dj_func_info = dj_func_info
        logging.info(
            f"Successfully initialized dj_func_info with {len(_global_dj_func_info)} operators"
        )
        return True
    except Exception as e:
        logging.error(f"Failed to initialize dj_func_info: {e}")
        return False


def get_dj_func_info():
    """Get current dj_func_info (lifecycle-aware)"""
    global _global_dj_func_info

    if _global_dj_func_info is None:
        logging.warning("dj_func_info not initialized, initializing now...")
        if not init_dj_func_info():
            # Fallback to direct import if initialization fails
            logging.warning("Falling back to direct import of dj_func_info")
            from .create_dj_func_info import dj_func_info

            return dj_func_info

    return _global_dj_func_info


def _build_vector_index():
    """Build vector index using fresh dj_func_info"""
    global _cached_vector_store, _cached_tools_info, _cached_content_hash

    dj_func_info = get_dj_func_info()

    tool_descriptions = [f"{t['class_name']}: {t['class_desc']}" for t in dj_func_info]

    from langchain_community.embeddings import DashScopeEmbeddings

    embeddings = DashScopeEmbeddings(
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
        model="text-embedding-v1",
    )

    metadatas = [{"index": i} for i in range(len(tool_descriptions))]
    vector_store = FAISS.from_texts(
        tool_descriptions,
        embeddings,
        metadatas=metadatas,
    )

    # Cache the results
    _cached_vector_store = vector_store
    _cached_tools_info = dj_func_info
    _cached_content_hash = _get_content_hash(dj_func_info)

    # Save to disk cache
    _save_cached_index()

    logging.info("Successfully built and cached vector index")


def retrieve_ops_vector(user_query, limit=20):
    """Tool retrieval using vector search with smart caching - returns list of tool names"""
    global _cached_vector_store, _cached_tools_info

    # Try to load from cache first, only rebuild if content changed
    if not _load_cached_index():
        logging.info("Building new vector index...")
        _build_vector_index()

    # Perform similarity search
    retrieved_tools = _cached_vector_store.similarity_search(
        user_query,
        k=limit,
    )
    retrieved_indices = [doc.metadata["index"] for doc in retrieved_tools]

    # Extract tool names from retrieved indices using cached tools info
    tool_names = []
    for raw_idx in retrieved_indices:
        tool_info = _cached_tools_info[raw_idx]
        tool_names.append(tool_info["class_name"])

    return tool_names

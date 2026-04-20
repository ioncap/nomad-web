import json
import os
import time
from flask import Blueprint, request, jsonify, Response
from qdrant_client import QdrantClient
from qdrant_client.http import models
from config import QDRANT_HOST, QDRANT_PORT, COLLECTION

_KB_BROWSER_HTML = None

def _get_browser_html():
    global _KB_BROWSER_HTML
    if _KB_BROWSER_HTML is None:
        path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'kb_browser.html')
        _KB_BROWSER_HTML = open(os.path.normpath(path)).read()
    return _KB_BROWSER_HTML

kb_bp = Blueprint('kb_manager', __name__, url_prefix='/kb')

@kb_bp.route('/browser')
def kb_browser():
    return Response(_get_browser_html(), content_type='text/html')

def get_client():
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

@kb_bp.route('/stats', methods=['GET'])
def kb_stats():
    try:
        client = get_client()
        info = client.get_collection(COLLECTION)
        points_count = client.count(COLLECTION).count
        stats = {
            "name": COLLECTION,
            "points_count": points_count,
            "status": info.status,
            "vector_size": info.config.params.vectors.size,
            "distance": str(info.config.params.vectors.distance),
            "indexed_vectors_count": info.indexed_vectors_count if hasattr(info, 'indexed_vectors_count') else points_count
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/documents', methods=['GET'])
def list_documents():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        query = request.args.get('q', '').strip()

        client = get_client()
        all_points = []
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            all_points.extend(points)
            if next_offset is None:
                break
            offset = next_offset

        if query:
            query_lower = query.lower()
            filtered = []
            for p in all_points:
                payload = p.payload or {}
                title = payload.get('article_title', '').lower()
                content = payload.get('content', '').lower()
                if query_lower in title or query_lower in content:
                    filtered.append(p)
            all_points = filtered

        total = len(all_points)
        start = (page - 1) * per_page
        end = start + per_page
        page_points = all_points[start:end]

        documents = []
        for p in page_points:
            payload = p.payload or {}
            documents.append({
                "id": p.id,
                "title": payload.get('article_title', 'Untitled'),
                "content_preview": payload.get('content', '')[:200] + ('...' if len(payload.get('content', '')) > 200 else ''),
                "source": payload.get('source', 'unknown'),
                "created_at": payload.get('generated_at', ''),
                "score": None
            })

        return jsonify({
            "documents": documents,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/documents/<doc_id>', methods=['GET'])
def get_document(doc_id):
    try:
        client = get_client()
        points = client.retrieve(
            collection_name=COLLECTION,
            ids=[doc_id],
            with_payload=True,
            with_vectors=False
        )
        if not points:
            return jsonify({"error": "Document not found"}), 404
        p = points[0]
        payload = p.payload or {}
        return jsonify({
            "id": p.id,
            "payload": payload,
            "content": payload.get('content', ''),
            "title": payload.get('article_title', 'Untitled')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    try:
        client = get_client()
        client.delete(
            collection_name=COLLECTION,
            points_selector=models.PointIdsList(points=[doc_id])
        )
        return jsonify({"status": "deleted", "id": doc_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/purge', methods=['POST'])
def purge_collection():
    try:
        data = request.get_json()
        if not data or data.get('confirm') != 'yes':
            return jsonify({"error": "Confirmation required"}), 400

        client = get_client()
        client.delete_collection(COLLECTION)
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(
                size=768,
                distance=models.Distance.COSINE
            )
        )
        return jsonify({"status": "collection purged and recreated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/export', methods=['GET'])
def export_collection():
    try:
        client = get_client()
        all_points = []
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            all_points.extend(points)
            if next_offset is None:
                break
            offset = next_offset

        export_data = [{"id": p.id, "payload": p.payload} for p in all_points]
        return jsonify(export_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

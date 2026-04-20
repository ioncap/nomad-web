import json
import os
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


def _parse_id(doc_id):
    """Qdrant IDs are either unsigned ints or UUID strings."""
    try:
        return int(doc_id)
    except (ValueError, TypeError):
        return doc_id


@kb_bp.route('/stats', methods=['GET'])
def kb_stats():
    try:
        client = get_client()
        info = client.get_collection(COLLECTION)
        points_count = client.count(COLLECTION, exact=False).count
        stats = {
            "name": COLLECTION,
            "points_count": points_count,
            "status": str(info.status),
            "vector_size": info.config.params.vectors.size,
            "distance": str(info.config.params.vectors.distance),
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_bp.route('/documents', methods=['GET'])
def list_documents():
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(max(5, int(request.args.get('per_page', 20))), 50)
        query = request.args.get('q', '').strip()
        client = get_client()

        if query:
            # Text search: scan up to SCAN_CAP docs, never load the full KB
            SCAN_CAP = 500
            query_lower = query.lower()
            matched = []
            offset = None
            scanned = 0
            while scanned < SCAN_CAP:
                batch = min(100, SCAN_CAP - scanned)
                points, next_offset = client.scroll(
                    collection_name=COLLECTION,
                    limit=batch,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in points:
                    payload = p.payload or {}
                    if (query_lower in payload.get('article_title', '').lower()
                            or query_lower in payload.get('content', '').lower()):
                        matched.append(p)
                scanned += len(points)
                if next_offset is None:
                    break
                offset = next_offset

            total = len(matched)
            start = (page - 1) * per_page
            page_points = matched[start:start + per_page]

        else:
            # No search: efficient cursor-based paging
            # Count is approximate but instant; avoids full scan
            total = client.count(COLLECTION, exact=False).count
            skip = (page - 1) * per_page

            # Walk to the correct page position with IDs-only (no payload = lightweight)
            offset = None
            skipped = 0
            while skipped < skip:
                batch = min(100, skip - skipped)
                ids_batch, next_offset = client.scroll(
                    collection_name=COLLECTION,
                    limit=batch,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                skipped += len(ids_batch)
                if not ids_batch or next_offset is None:
                    return jsonify({
                        "documents": [], "total": total, "page": page,
                        "per_page": per_page,
                        "pages": max(1, (total + per_page - 1) // per_page),
                    })
                offset = next_offset

            # Fetch only the current page with full payload
            page_points, _ = client.scroll(
                collection_name=COLLECTION,
                limit=per_page,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

        documents = []
        for p in page_points:
            payload = p.payload or {}
            content = payload.get('content', '')
            documents.append({
                "id": str(p.id),
                "title": payload.get('article_title', 'Untitled'),
                "content_preview": content[:200] + ('...' if len(content) > 200 else ''),
                "source": payload.get('source', 'unknown'),
                "created_at": payload.get('generated_at', ''),
            })

        pages = max(1, (total + per_page - 1) // per_page)
        return jsonify({
            "documents": documents,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_bp.route('/documents/<doc_id>', methods=['GET'])
def get_document(doc_id):
    try:
        client = get_client()
        points = client.retrieve(
            collection_name=COLLECTION,
            ids=[_parse_id(doc_id)],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return jsonify({"error": "Document not found"}), 404
        p = points[0]
        payload = p.payload or {}
        return jsonify({
            "id": str(p.id),
            "payload": payload,
            "content": payload.get('content', ''),
            "title": payload.get('article_title', 'Untitled'),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_bp.route('/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    try:
        client = get_client()
        client.delete(
            collection_name=COLLECTION,
            points_selector=models.PointIdsList(points=[_parse_id(doc_id)]),
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
            vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE),
        )
        return jsonify({"status": "collection purged and recreated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_bp.route('/export', methods=['GET'])
def export_collection():
    """Stream the full KB as JSON without buffering it all in RAM."""
    client = get_client()

    def generate():
        yield '[\n'
        offset = None
        first = True
        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                if not first:
                    yield ',\n'
                yield json.dumps({"id": str(p.id), "payload": p.payload}, ensure_ascii=False)
                first = False
            if next_offset is None:
                break
            offset = next_offset
        yield '\n]'

    return Response(
        generate(),
        content_type='application/json; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="kb_export.json"'},
    )

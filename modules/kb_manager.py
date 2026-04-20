import json
import time
from flask import Blueprint, request, jsonify
from qdrant_client import QdrantClient
from qdrant_client.http import models
from config import QDRANT_HOST, QDRANT_PORT, COLLECTION

kb_bp = Blueprint('kb_manager', __name__, url_prefix='/kb')

def get_client():
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

@kb_bp.route('/stats', methods=['GET'])
def kb_stats():
    """Uitgebreide statistieken over de collectie."""
    try:
        client = get_client()
        info = client.get_collection(COLLECTION)
        points_count = client.count(COLLECTION).count
        # Optioneel: schatting opslagruimte (niet direct via API)
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
    """Lijst van documenten met paginering en optionele zoekterm."""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        query = request.args.get('q', '').strip()
        
        client = get_client()
        # Scroll door alle punten (eenvoudige aanpak; bij grote aantallen is cursor nodig)
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
        
        # Filter op zoekterm (in payload.content of payload.article_title)
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
        
        # Transformeer naar eenvoudig JSON-formaat
        documents = []
        for p in page_points:
            payload = p.payload or {}
            documents.append({
                "id": p.id,
                "title": payload.get('article_title', 'Untitled'),
                "content_preview": payload.get('content', '')[:200] + ('...' if len(payload.get('content', '')) > 200 else ''),
                "source": payload.get('source', 'unknown'),
                "created_at": payload.get('generated_at', ''),
                "score": None  # geen score bij lijstweergave
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
    """Haal volledige inhoud van één document op."""
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
    """Verwijder een document uit de collectie."""
    try:
        client = get_client()
        client.delete(
            collection_name=COLLECTION,
            points_selector=models.PointIdsList(
                points=[doc_id]
            )
        )
        return jsonify({"status": "deleted", "id": doc_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/purge', methods=['POST'])
def purge_collection():
    """Verwijder alle documenten uit de collectie (bevestiging vereist)."""
    try:
        data = request.get_json()
        if not data or data.get('confirm') != 'yes':
            return jsonify({"error": "Confirmation required"}), 400
        
        client = get_client()
        # Qdrant heeft geen truncate; we hercreëren de collectie
        client.delete_collection(COLLECTION)
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(
                size=768,  # nomic-embed-text dimensie
                distance=models.Distance.COSINE
            )
        )
        return jsonify({"status": "collection purged and recreated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/export', methods=['GET'])
def export_collection():
    """Exporteer alle documenten als JSON (download)."""
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
        
        export_data = []
        for p in all_points:
            export_data.append({
                "id": p.id,
                "payload": p.payload
            })
        
        return jsonify(export_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

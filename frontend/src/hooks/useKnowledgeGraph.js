import { useState, useCallback } from 'react';
import { API, apiFetch } from '../components/utils';

/**
 * Manages the concept knowledge graph (nodes + edges)
 * and the node mastery status update handler.
 *
 * @param {string} id - Notebook ID
 */
export function useKnowledgeGraph(id) {
    const [graphNodes, setGraphNodes] = useState([]);
    const [graphEdges, setGraphEdges] = useState([]);

    const handleNodeStatusChange = useCallback(async (node, status) => {
        setGraphNodes(prev => prev.map(n => n.id === node.id ? { ...n, status } : n));
        try {
            await apiFetch(`${API}/notebooks/${id}/graph/update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ concept_name: node.label, status }),
            });
        } catch { }
    }, [id]);

    return {
        graphNodes, setGraphNodes,
        graphEdges, setGraphEdges,
        handleNodeStatusChange,
    };
}

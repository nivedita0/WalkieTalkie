import React, { useState, useEffect } from 'react';
import { useGeolocation } from '../hooks/useGeolocation';
import { calculateDistance } from '../utils/geo';
import { getNodes, markNodeVisited, resetVisited } from '../db/db';
import { narrator } from '../services/NarratorService';
import { generateIntro } from '../utils/storyTemplating';

/**
 * Locality-first walking tour: explore by neighborhood stop, not turn-by-turn directions.
 * When you're physically near a stop (~20m), the story plays automatically.
 *
 * @param {string} city — Trip city (always from the toolbar).
 * @param {string|null} [areaLabel] — Neighborhood / day locality from the itinerary when available.
 */
export default function SpatialTrigger({ city = "this city", areaLabel = null, llmTier = "small", onClose }) {
    const primaryArea =
        typeof areaLabel === "string" && areaLabel.trim().length > 0 ? areaLabel.trim() : city;
    const showCityLine =
        typeof areaLabel === "string" &&
        areaLabel.trim().length > 0 &&
        city &&
        areaLabel.trim().toLowerCase() !== city.trim().toLowerCase();
    const { location, error } = useGeolocation();
    const [nodes, setNodes] = useState([]);
    const [targetNode, setTargetNode] = useState(null);
    const [distance, setDistance] = useState(null);
    const [narrating, setNarrating] = useState(null);

    useEffect(() => {
        loadNodes();
    }, []);

    const loadNodes = async () => {
        const data = await getNodes();
        setNodes(data);
    };

    const handleReset = async () => {
        await resetVisited();
        loadNodes();
    };

    useEffect(() => {
        if (targetNode && location) {
            const dist = calculateDistance(
                location.lat,
                location.lng,
                targetNode.lat,
                targetNode.lng
            );
            setDistance(Math.round(dist));

            if (dist <= 20 && !targetNode.locked && !narrating) {
                triggerNarration(targetNode);
            }
        }
    }, [location, targetNode, narrating]);

    const triggerNarration = async (node) => {
        setNarrating(node.title);
        narrator.currentTopic = node.title;

        setTargetNode(prev => ({ ...prev, visited: true, locked: true }));

        await markNodeVisited(node.id);
        loadNodes();

        const introText = generateIntro(node.title);
        let personaStory = "";
        try {
            const res = await fetch("/api/walk-story", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    city,
                    place_title: node.title,
                    anecdote: node.anecdote || "",
                    llm_tier: llmTier,
                }),
            });
            if (res.ok) {
                const payload = await res.json();
                personaStory = (payload?.story || "").trim();
            }
        } catch {
            // Graceful fallback below.
        }
        const fullText = personaStory || (introText + " " + (node.anecdote || ""));
        narrator.speak(fullText, () => setNarrating(null));
    };

    const stopNarration = () => {
        narrator.cancel();
        setNarrating(null);
    };

    return (
        <div style={styles.overlay}>
            <div style={styles.container}>
                <button style={styles.closeBtn} onClick={() => { stopNarration(); onClose(); }}>✕</button>
                <h2 style={styles.title}>Walk · {primaryArea}</h2>
                {showCityLine ? (
                    <p style={styles.cityLine}>{city}</p>
                ) : null}
                <p style={styles.blurb}>
                    Choose a stop in this area. Wander the block; when you’re within about 20m, the story unlocks automatically.
                </p>

                {error && <p style={styles.error}>Location error: {error}</p>}
                {!location && !error && <p style={styles.info}>Finding your position…</p>}
                {location && <p style={styles.info}>Location accuracy ~{Math.round(location.accuracy)}m</p>}

                {narrating ? (
                    <div style={styles.narratingBox}>
                        <h3>🔊 Story: {narrating}</h3>
                        <div className="typing" style={{ justifyContent: 'center', margin: '20px 0' }}>
                            <div className="dot" /><div className="dot" /><div className="dot" />
                        </div>
                        <button style={styles.stopBtn} onClick={stopNarration}>Stop</button>
                    </div>
                ) : (
                    targetNode ? (
                        <div style={styles.guidingBox}>
                            <h3>Walking stop: {targetNode.title}</h3>
                            <p style={{ fontSize: '15px', color: '#c4b69a', marginBottom: '12px', lineHeight: 1.5 }}>
                                Stroll this part of town — no driving directions, just local context when you arrive.
                            </p>
                            <p style={{ fontSize: '36px', margin: '10px 0', color: '#c8a96e' }}>
                                {distance !== null ? `~${distance} m` : '…'}
                            </p>
                            <p style={{ fontSize: '13px', color: '#8a7d66', marginBottom: '16px' }}>
                                {distance !== null && distance > 20
                                    ? 'Move closer to this corner or block to unlock the narration (~20m).'
                                    : distance !== null && distance <= 20
                                        ? 'You’re in range — story should play, or tap below.'
                                        : null}
                            </p>
                            {distance !== null && distance <= 20 && targetNode.visited && (
                                <button
                                    style={{ ...styles.btn, marginBottom: '12px', background: 'rgba(200, 169, 110, 0.1)' }}
                                    onClick={() => triggerNarration(targetNode)}
                                >
                                    Play story again 🎧
                                </button>
                            )}
                            <button style={styles.btn} onClick={() => setTargetNode(null)}>Pick another stop</button>
                        </div>
                    ) : (
                        <div style={styles.list}>
                            <h3 style={{ marginBottom: '10px', color: '#c4b69a', fontSize: '15px' }}>Stops in your plan (same-day area)</h3>
                            {nodes.map(n => (
                                <div key={n.id} style={styles.nodeCard}>
                                    <div>
                                        <strong style={{ fontSize: '14px' }}>{n.title}</strong>
                                        {n.visited && <span style={styles.badge}>Heard</span>}
                                    </div>
                                    <button
                                        style={styles.navBtn}
                                        onClick={() => setTargetNode(n)}
                                    >
                                        Walk here
                                    </button>
                                </div>
                            ))}
                            <div style={styles.actions}>
                                <button style={{ ...styles.btn, marginTop: '20px' }} onClick={handleReset}>Reset stops</button>
                            </div>
                        </div>
                    )
                )}
            </div>
        </div>
    );
}

const styles = {
    overlay: {
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(15, 14, 11, 0.95)',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        zIndex: 100, fontFamily: "'Source Serif 4', serif", color: '#f0ead6'
    },
    container: {
        backgroundColor: '#1a1810',
        border: '1px solid #c8a96e44',
        borderRadius: '16px',
        padding: '24px',
        width: '90%', maxWidth: '400px',
        position: 'relative',
        boxShadow: '0 20px 40px rgba(0,0,0,0.5)'
    },
    title: {
        fontFamily: "'Playfair Display', serif",
        color: '#c8a96e',
        marginBottom: '6px',
        marginTop: 0
    },
    cityLine: {
        fontSize: '13px',
        color: '#8a7d66',
        marginBottom: '10px',
        marginTop: 0,
        letterSpacing: '0.02em'
    },
    blurb: {
        fontSize: '13px',
        color: '#8a7d66',
        lineHeight: 1.55,
        marginBottom: '18px',
        marginTop: 0
    },
    closeBtn: {
        position: 'absolute', top: '16px', right: '16px',
        background: 'transparent', border: 'none', color: '#c8a96e',
        fontSize: '20px', cursor: 'pointer'
    },
    info: { fontSize: '12px', color: '#8a7d66', marginBottom: '16px' },
    error: { color: '#ff6b6b', fontSize: '14px' },
    list: {
        maxHeight: '300px', overflowY: 'auto'
    },
    nodeCard: {
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px', border: '1px solid #2a2820', borderRadius: '8px',
        marginBottom: '8px', background: '#0f0e0b'
    },
    badge: {
        fontSize: '10px', background: '#c8a96e33', color: '#c8a96e',
        padding: '2px 6px', borderRadius: '4px', marginLeft: '8px', verticalAlign: 'middle'
    },
    navBtn: {
        background: '#c8a96e', color: '#0f0e0b', border: 'none',
        padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold'
    },
    btn: {
        background: 'transparent', color: '#c8a96e', border: '1px solid #c8a96e',
        padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', width: '100%'
    },
    stopBtn: {
        background: '#8b1414', color: '#fff', border: 'none',
        padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', marginTop: '16px'
    },
    narratingBox: {
        textAlign: 'center', padding: '20px 0'
    },
    guidingBox: {
        textAlign: 'center', padding: '20px 0'
    },
    actions: {}
};

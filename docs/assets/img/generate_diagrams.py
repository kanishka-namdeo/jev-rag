"""
Generate high-quality diagrams for Jev-RAG documentation.
Uses matplotlib for professional, publication-quality charts.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, Polygon, ArrowStyle
from matplotlib.collections import PatchCollection
import matplotlib.patheffects as path_effects
import numpy as np

# Professional color palette
COLORS = {
    'bg': '#0B0F19',
    'bg_card': '#151B2B',
    'bg_elevated': '#1E2538',
    'border': '#2D3748',
    
    'primary': '#3B82F6',
    'primary_light': '#60A5FA',
    'primary_dark': '#2563EB',
    
    'success': '#10B981',
    'success_light': '#34D399',
    'success_dark': '#059669',
    
    'warning': '#F59E0B',
    'warning_light': '#FBBF24',
    'warning_dark': '#D97706',
    
    'accent': '#8B5CF6',
    'accent_light': '#A78BFA',
    
    'text': '#F9FAFB',
    'text_secondary': '#9CA3AF',
    'text_muted': '#6B7280',
}

def style_text(ax, text, x, y, fontsize=10, color='white', fontweight='normal', 
               ha='center', va='center', glow=False):
    """Add styled text with optional glow effect."""
    t = ax.text(x, y, text, fontsize=fontsize, color=color, fontweight=fontweight,
                ha=ha, va=va, zorder=10)
    if glow:
        t.set_path_effects([path_effects.withStroke(linewidth=3, foreground='black', alpha=0.5)])
    return t

def draw_card(ax, x, y, width, height, title, subtitle=None, color=COLORS['bg_card'],
              border_color=COLORS['border'], title_size=10, subtitle_size=8,
              glow=False, shadow=True):
    """Draw a professional card with title and optional subtitle."""
    # Shadow
    if shadow:
        shadow_rect = FancyBboxPatch((x+0.05, y-0.05), width, height,
                                    boxstyle="round,pad=0.02,rounding_size=0.15",
                                    facecolor='black', alpha=0.3, zorder=1)
        ax.add_patch(shadow_rect)
    
    # Main card
    card = FancyBboxPatch((x, y), width, height,
                         boxstyle="round,pad=0.02,rounding_size=0.15",
                         facecolor=color, edgecolor=border_color, 
                         linewidth=2, zorder=2)
    ax.add_patch(card)
    
    # Glow effect
    if glow:
        glow_rect = FancyBboxPatch((x-0.02, y-0.02), width+0.04, height+0.04,
                                  boxstyle="round,pad=0.02,rounding_size=0.15",
                                  facecolor='none', edgecolor=color, 
                                  linewidth=4, alpha=0.3, zorder=1)
        ax.add_patch(glow_rect)
    
    # Title
    style_text(ax, title, x + width/2, y + height - 0.25, 
              fontsize=title_size, color=COLORS['text'], fontweight='bold')
    
    # Subtitle
    if subtitle:
        style_text(ax, subtitle, x + width/2, y + height/2, 
                  fontsize=subtitle_size, color=COLORS['text_secondary'])

def draw_connector(ax, x1, y1, x2, y2, color='white', lw=2, style='->', 
                   label=None, label_pos=0.5, curved=False):
    """Draw a connector arrow between two points."""
    if curved:
        style = '->,head_width=0.3,head_length=0.2'
        connection = 'arc3,rad=0.2'
    else:
        connection = 'arc3,rad=0'
    
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
               arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                              connectionstyle=connection),
               zorder=5)
    
    if label:
        lx = x1 + (x2 - x1) * label_pos
        ly = y1 + (y2 - y1) * label_pos
        style_text(ax, label, lx, ly + 0.15, fontsize=8, 
                  color=color, fontweight='bold')

def create_results_chart():
    """Create a professional benchmark results chart."""
    fig, ax = plt.subplots(figsize=(16, 9), dpi=200)
    fig.patch.set_facecolor(COLORS['bg'])
    ax.set_facecolor(COLORS['bg'])
    
    # Title area
    ax.text(0.5, 0.96, 'Jev-RAG Benchmark Results', 
           transform=ax.transAxes, fontsize=28, fontweight='bold',
           color=COLORS['text'], ha='center')
    ax.text(0.5, 0.92, 'Comparing pipeline versions across key metrics', 
           transform=ax.transAxes, fontsize=14, color=COLORS['text_secondary'], 
           ha='center', style='italic')
    
    # Data
    metrics = ['Answer\nRelevance', 'Context\nPrecision', 'Groundedness', 
               'Citation\nAccuracy', 'Latency\n(ms)']
    
    # Raw scores
    v1_raw = [0.72, 0.65, 0.58, 0.52, 850]
    v2_raw = [0.78, 0.71, 0.71, 0.65, 720]
    v3_raw = [0.88, 0.85, 0.91, 0.86, 600]
    hybrid_raw = [0.92, 0.89, 0.94, 0.90, 550]
    
    # Normalize latency (invert: lower ms = higher score)
    max_latency = 1000
    v1_scores = v1_raw.copy()
    v2_scores = v2_raw.copy()
    v3_scores = v3_raw.copy()
    hybrid_scores = hybrid_raw.copy()
    
    v1_scores[4] = (max_latency - v1_raw[4]) / max_latency * 100
    v2_scores[4] = (max_latency - v2_raw[4]) / max_latency * 100
    v3_scores[4] = (max_latency - v3_raw[4]) / max_latency * 100
    hybrid_scores[4] = (max_latency - hybrid_raw[4]) / max_latency * 100
    
    x = np.arange(len(metrics))
    width = 0.16
    
    # Create gradient-like bars
    bar_colors = {
        'v1': '#64748B',
        'v2': COLORS['primary'],
        'v3': COLORS['success'],
        'hybrid': COLORS['accent']
    }
    
    bars1 = ax.bar(x - 1.5*width, v1_scores, width, label='v1 (Baseline)', 
                   color=bar_colors['v1'], alpha=0.7, edgecolor='white', 
                   linewidth=1, zorder=3)
    bars2 = ax.bar(x - 0.5*width, v2_scores, width, label='v2 (7-slot Pipeline)', 
                   color=bar_colors['v2'], alpha=0.85, edgecolor='white', 
                   linewidth=1, zorder=3)
    bars3 = ax.bar(x + 0.5*width, v3_scores, width, label='v3 (Escalation Gate)', 
                   color=bar_colors['v3'], alpha=0.9, edgecolor='white', 
                   linewidth=1, zorder=3)
    bars4 = ax.bar(x + 1.5*width, hybrid_scores, width, label='Hybrid (Current)', 
                   color=bar_colors['hybrid'], alpha=1.0, edgecolor='white', 
                   linewidth=2, zorder=3)
    
    # Add value labels
    def add_value_labels(bars, values, raw_values):
        for bar, val, raw in zip(bars, values, raw_values):
            height = bar.get_height()
            if isinstance(raw, int):  # latency
                label = f'{raw}'
                y_offset = -12
            else:
                label = f'{raw:.2f}'
                y_offset = 5
            
            ax.annotate(label,
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, y_offset),
                       textcoords="offset points",
                       ha='center', va='bottom' if y_offset > 0 else 'top',
                       fontsize=9, color='white', fontweight='bold',
                       zorder=10)
    
    add_value_labels(bars1, v1_scores, v1_raw)
    add_value_labels(bars2, v2_scores, v2_raw)
    add_value_labels(bars3, v3_scores, v3_raw)
    add_value_labels(bars4, hybrid_scores, hybrid_raw)
    
    # Styling
    ax.set_ylabel('Score / Normalized Latency', fontsize=13, fontweight='bold', 
                  color=COLORS['text_secondary'], labelpad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=12, color=COLORS['text_secondary'], 
                       fontweight='bold')
    ax.tick_params(axis='y', colors=COLORS['text_muted'], labelsize=10)
    
    # Legend
    legend = ax.legend(loc='upper left', framealpha=0.95, 
                      facecolor=COLORS['bg_card'], edgecolor=COLORS['border'], 
                      fontsize=11, fancybox=True, shadow=True)
    for text in legend.get_texts():
        text.set_color(COLORS['text'])
    
    # Grid
    ax.set_ylim(0, 105)
    ax.yaxis.grid(True, linestyle='--', alpha=0.2, color=COLORS['border'])
    ax.set_axisbelow(True)
    
    # Remove spines
    for spine in ax.spines.values():
        spine.set_color(COLORS['border'])
        spine.set_linewidth(1.5)
    
    plt.tight_layout(rect=[0, 0.05, 1, 0.9])
    plt.savefig('v3-results-chart.png', dpi=200, bbox_inches='tight', 
                facecolor=COLORS['bg'], edgecolor='none', pad_inches=0.3)
    plt.close()
    print("Created v3-results-chart.png")


def create_escalation_gate_diagram():
    """Create a professional escalation gate flow diagram."""
    fig, ax = plt.subplots(figsize=(16, 11), dpi=200)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 11)
    fig.patch.set_facecolor(COLORS['bg'])
    ax.set_facecolor(COLORS['bg'])
    ax.axis('off')
    
    # Title
    style_text(ax, 'Jev-RAG Escalation Gate', 8, 10.3, fontsize=26, 
              color=COLORS['text'], fontweight='bold')
    style_text(ax, 'Context Sufficiency Decision Flow', 8, 9.8, fontsize=14, 
              color=COLORS['text_secondary'])
    
    # Input section
    draw_card(ax, 1, 7.5, 3.5, 1.5, 'Reranked Passages', 
             'After jev-score reranking', color=COLORS['primary_dark'],
             border_color=COLORS['primary'])
    
    # Arrow down
    draw_connector(ax, 2.75, 7.5, 2.75, 6.3, color=COLORS['text_secondary'])
    
    # Score Features
    draw_card(ax, 1, 4.8, 3.5, 1.5, 'Score Features', 
             'top_score · score_gap · coverage',
             color=COLORS['bg_elevated'], border_color=COLORS['accent'])
    
    # Arrow to decision
    draw_connector(ax, 4.5, 5.55, 6.2, 5.55, color=COLORS['text_secondary'])
    
    # Decision diamond
    diamond = Polygon([(8, 6.8), (9.5, 5.55), (8, 4.3), (6.5, 5.55)], 
                     facecolor=COLORS['warning'], edgecolor='white', 
                     linewidth=3, zorder=5)
    ax.add_patch(diamond)
    style_text(ax, 'CONTEXT', 8, 5.8, fontsize=11, color='white', fontweight='bold')
    style_text(ax, 'SUFFICIENT?', 8, 5.4, fontsize=11, color='white', fontweight='bold')
    
    # YES path (up-right)
    draw_connector(ax, 9.3, 6.2, 11.5, 7.5, color=COLORS['success'], lw=3)
    style_text(ax, 'YES', 10.2, 7.1, fontsize=12, color=COLORS['success'], 
              fontweight='bold')
    
    # Sufficient box
    draw_card(ax, 11.5, 7.5, 3.5, 1.5, 'Context Sufficient', 
             'Route to qwen3.7-plus (fast)',
             color=COLORS['success_dark'], border_color=COLORS['success'],
             glow=True)
    
    # NO path (down-right)
    draw_connector(ax, 9.3, 4.9, 11.5, 2.5, color=COLORS['warning'], lw=3)
    style_text(ax, 'NO', 10.2, 3.5, fontsize=12, color=COLORS['warning'], 
              fontweight='bold')
    
    # Insufficient box
    draw_card(ax, 11.5, 1, 3.5, 1.5, 'Context Insufficient', 
             'Route to qwen3.6-plus (reasoning)',
             color=COLORS['warning_dark'], border_color=COLORS['warning'],
             glow=True)
    
    # Arrows to Model Router
    draw_connector(ax, 13.25, 7.5, 13.25, 5.8, color=COLORS['text_secondary'])
    draw_connector(ax, 13.25, 2.5, 13.25, 4.2, color=COLORS['text_secondary'])
    
    # Model Router
    draw_card(ax, 10.5, 4.5, 2.5, 1.2, 'Model Router', 
             'Select LLM based on gate',
             color=COLORS['accent'], border_color=COLORS['accent_light'])
    
    # Arrow to Final Answer
    draw_connector(ax, 10.5, 5.1, 5.5, 5.1, color=COLORS['text_secondary'])
    
    # Final Answer
    draw_card(ax, 2, 4.2, 3.5, 1.8, 'Final Answer', 
             'Cited response with\nGroundedness Badge',
             color=COLORS['success_dark'], border_color=COLORS['success_light'],
             glow=True, title_size=12)
    
    # Threshold info panel
    info_bg = FancyBboxPatch((0.5, 0.3), 4, 1.8,
                            boxstyle="round,pad=0.02,rounding_size=0.1",
                            facecolor=COLORS['bg_card'], 
                            edgecolor=COLORS['border'], linewidth=2)
    ax.add_patch(info_bg)
    
    style_text(ax, 'Gate Thresholds', 2.5, 1.8, fontsize=12, 
              color=COLORS['text'], fontweight='bold')
    style_text(ax, 'score_threshold = 0.75', 2.5, 1.35, fontsize=10, 
              color=COLORS['text_secondary'])
    style_text(ax, 'gap_threshold = 0.15', 2.5, 0.95, fontsize=10, 
              color=COLORS['text_secondary'])
    style_text(ax, 'coverage_min = 0.60', 2.5, 0.55, fontsize=10, 
              color=COLORS['text_secondary'])
    
    # Legend
    legend_y = 0.8
    legend_items = [
        (COLORS['primary'], 'Input'),
        (COLORS['accent'], 'Processing'),
        (COLORS['success'], 'Success Path'),
        (COLORS['warning'], 'Escalation Path'),
    ]
    
    for i, (color, label) in enumerate(legend_items):
        x_pos = 6 + i * 2.5
        rect = Rectangle((x_pos, legend_y - 0.1), 0.35, 0.25, 
                         facecolor=color, edgecolor='white', linewidth=1.5)
        ax.add_patch(rect)
        style_text(ax, label, x_pos + 0.55, legend_y, fontsize=10, 
                  color=COLORS['text_secondary'], va='center')
    
    plt.tight_layout()
    plt.savefig('escalation-gate-v2.png', dpi=200, bbox_inches='tight',
                facecolor=COLORS['bg'], edgecolor='none', pad_inches=0.2)
    plt.close()
    print("Created escalation-gate-v2.png")


def create_architecture_diagram():
    """Create a professional v3 architecture diagram."""
    fig, ax = plt.subplots(figsize=(18, 10), dpi=200)
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 10)
    fig.patch.set_facecolor(COLORS['bg'])
    ax.set_facecolor(COLORS['bg'])
    ax.axis('off')
    
    # Title
    style_text(ax, 'Jev-RAG v3 Architecture', 9, 9.5, fontsize=28, 
              color=COLORS['text'], fontweight='bold')
    style_text(ax, 'Local-First Hybrid RAG System', 9, 9.0, fontsize=14, 
              color=COLORS['text_secondary'])
    
    # Section 1: Document Ingestion (left)
    section1_bg = FancyBboxPatch((0.3, 3.5), 4, 5,
                                boxstyle="round,pad=0.02,rounding_size=0.1",
                                facecolor=COLORS['bg_card'], 
                                edgecolor=COLORS['border'], linewidth=2, alpha=0.5)
    ax.add_patch(section1_bg)
    style_text(ax, 'Document Ingestion', 2.3, 8.2, fontsize=13, 
              color=COLORS['text'], fontweight='bold')
    
    draw_card(ax, 0.5, 6.5, 3.5, 1.3, 'Upload Documents', 
             'PDF, DOCX, TXT, MD', color=COLORS['bg_elevated'])
    draw_connector(ax, 2.25, 6.5, 2.25, 5.9, color=COLORS['text_secondary'])
    
    draw_card(ax, 0.5, 4.6, 3.5, 1.3, 'markitdown + Chunk', 
             'Structure-aware splitting', color=COLORS['bg_elevated'])
    draw_connector(ax, 2.25, 4.6, 2.25, 4.0, color=COLORS['text_secondary'])
    
    draw_card(ax, 0.5, 2.7, 3.5, 1.3, 'fastembed (ONNX)', 
             'Local CPU embeddings', color=COLORS['bg_elevated'])
    
    # ChromaDB
    draw_card(ax, 0.5, 0.8, 3.5, 1.5, 'ChromaDB', 
             'Embedded vector store\n+ BM25 index',
             color='#0c4a6e', border_color=COLORS['primary_light'],
             title_size=11)
    
    # Section 2: Query Processing (middle-left)
    section2_bg = FancyBboxPatch((4.8, 3.5), 4, 5,
                                boxstyle="round,pad=0.02,rounding_size=0.1",
                                facecolor=COLORS['bg_card'], 
                                edgecolor=COLORS['border'], linewidth=2, alpha=0.5)
    ax.add_patch(section2_bg)
    style_text(ax, 'Query Processing', 6.8, 8.2, fontsize=13, 
              color=COLORS['text'], fontweight='bold')
    
    draw_card(ax, 5, 6.5, 3.5, 1.3, 'User Query', 
             'Natural language input', color=COLORS['accent'])
    draw_connector(ax, 6.75, 6.5, 6.75, 5.9, color=COLORS['text_secondary'])
    
    draw_card(ax, 5, 4.6, 3.5, 1.3, 'Embed + Retrieve', 
             'Hybrid BM25 || Dense', color=COLORS['bg_elevated'])
    draw_connector(ax, 6.75, 4.6, 6.75, 4.0, color=COLORS['text_secondary'])
    
    draw_card(ax, 5, 2.7, 3.5, 1.3, 'Cross-Encoder Rerank', 
             'Top-10 → Top-4 passages', color=COLORS['bg_elevated'])
    
    # Connection from ingestion to query
    draw_connector(ax, 4, 1.55, 5, 1.55, color=COLORS['text_secondary'])
    
    # Section 3: Pipeline Fork (center)
    fork_circle = Circle((10.5, 5.5), 0.4, facecolor=COLORS['bg_elevated'], 
                        edgecolor='white', linewidth=3, zorder=10)
    ax.add_patch(fork_circle)
    ax.text(10.5, 5.5, 'F', fontsize=14, color='white', 
           fontweight='bold', ha='center', va='center', zorder=11)
    
    draw_connector(ax, 8.5, 3.35, 10.2, 5.2, color=COLORS['text_secondary'])
    
    # Traditional Pipeline (top path)
    draw_card(ax, 11.5, 7.5, 3, 1.5, 'Traditional Pipeline', 
             'Top-4 → Cloud LLM',
             color=COLORS['primary_dark'], border_color=COLORS['primary'],
             title_size=11)
    
    draw_connector(ax, 10.8, 5.8, 11.8, 7.2, color=COLORS['primary'], lw=2.5)
    style_text(ax, 'Simple', 11.0, 6.6, fontsize=9, color=COLORS['primary'])
    
    draw_card(ax, 15, 7.5, 2.5, 1.5, 'Cloud LLM', 
             'qwen3.7-plus\nSystem Two',
             color='#1e1b4b', border_color=COLORS['accent'],
             title_size=11)
    
    draw_connector(ax, 14.5, 8.25, 15, 8.25, color=COLORS['primary'])
    
    # Hybrid Pipeline (bottom path)
    hybrid_bg = FancyBboxPatch((11.3, 0.5), 4.2, 5.5,
                              boxstyle="round,pad=0.02,rounding_size=0.1",
                              facecolor='#064e3b', 
                              edgecolor=COLORS['success'], linewidth=3, alpha=0.3)
    ax.add_patch(hybrid_bg)
    
    style_text(ax, 'Hybrid Pipeline (Jev-Style)', 13.4, 5.7, fontsize=13, 
              color=COLORS['success_light'], fontweight='bold')
    
    draw_connector(ax, 10.8, 5.2, 11.8, 4.2, color=COLORS['success'], lw=2.5)
    style_text(ax, 'Complex', 11.0, 4.6, fontsize=9, color=COLORS['success'])
    
    # Steps in hybrid
    steps = [
        ('1. Rerank Passages', 4.8),
        ('2. Escalation Gate', 3.8),
        ('3. Model Router', 2.8),
        ('4. Verify Groundedness', 1.8),
    ]
    
    for text, y_pos in steps:
        draw_card(ax, 11.5, y_pos - 0.4, 3.8, 0.9, text, 
                 color=COLORS['success_dark'], border_color=COLORS['success'],
                 title_size=10)
        if y_pos > 2:
            draw_connector(ax, 13.4, y_pos - 0.4, 13.4, y_pos - 0.9, 
                          color=COLORS['success_light'])
    
    # Response section (right)
    draw_card(ax, 15, 4.5, 2.5, 3.5, 'Response', 
             'SSE Stream\nTrace Panel\nCitations\nGroundedness',
             color=COLORS['bg_elevated'], border_color=COLORS['border'],
             title_size=11)
    
    # Arrows to response
    draw_connector(ax, 17.5, 8.25, 17.5, 6.5, color=COLORS['primary'])
    draw_connector(ax, 17.5, 6.5, 17.5, 5.5, color=COLORS['primary'])
    draw_connector(ax, 17.5, 5.5, 17.5, 4.5, color=COLORS['text_secondary'])
    
    draw_connector(ax, 15.3, 1.8, 15.3, 3.5, color=COLORS['success'])
    draw_connector(ax, 15.3, 3.5, 15, 3.5, color=COLORS['success'])
    
    # Legend
    legend_items = [
        (COLORS['primary'], 'Traditional'),
        (COLORS['success'], 'Hybrid (Jev-Style)'),
        (COLORS['accent'], 'Cloud'),
        (COLORS['bg_elevated'], 'Local'),
    ]
    
    for i, (color, label) in enumerate(legend_items):
        x_pos = 5.5 + i * 2.8
        rect = Rectangle((x_pos, 0.3), 0.4, 0.3, 
                         facecolor=color, edgecolor='white', linewidth=2)
        ax.add_patch(rect)
        style_text(ax, label, x_pos + 0.6, 0.45, fontsize=10, 
                  color=COLORS['text_secondary'], va='center')
    
    style_text(ax, 'Everything except Cloud LLM runs locally', 16.5, 0.45, 
              fontsize=9, color=COLORS['text_muted'], ha='right')
    
    plt.tight_layout(pad=0.3)
    plt.savefig('v3-architecture-v2.png', dpi=200, bbox_inches='tight',
                facecolor=COLORS['bg'], edgecolor='none', pad_inches=0.2)
    plt.close()
    print("Created v3-architecture-v2.png")


if __name__ == '__main__':
    print("Generating Jev-RAG diagrams...")
    print()
    
    create_results_chart()
    create_escalation_gate_diagram()
    create_architecture_diagram()
    
    print()
    print("All diagrams generated successfully!")

"""
Generate high-quality diagrams for Jev-RAG documentation.
Uses matplotlib for professional, publication-quality charts.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle
import numpy as np

# Set up the style
plt.style.use('dark_background')
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Segoe UI', 'Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['axes.facecolor'] = '#0f172a'
plt.rcParams['figure.facecolor'] = '#0f172a'
plt.rcParams['text.color'] = '#f8fafc'
plt.rcParams['axes.labelcolor'] = '#94a3b8'
plt.rcParams['xtick.color'] = '#94a3b8'
plt.rcParams['ytick.color'] = '#94a3b8'

COLORS = {
    'bg': '#0f172a',
    'bg_light': '#1e293b',
    'traditional': '#0ea5e9',
    'hybrid': '#10b981',
    'hybrid_dark': '#059669',
    'local': '#f59e0b',
    'cloud': '#6366f1',
    'accent': '#8b5cf6',
    'text': '#f8fafc',
    'text_muted': '#94a3b8',
    'border': '#334155',
}

def create_results_chart():
    """Create the v3 results comparison chart."""
    fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
    ax.set_facecolor(COLORS['bg'])
    
    # Data
    metrics = ['Answer\nRelevance', 'Context\nPrecision', 'Groundedness\n(Faithfulness)', 
               'Citation\nAccuracy', 'Latency\n(ms, lower=better)']
    v1_scores = [0.72, 0.65, 0.58, 0.52, 850]
    v2_scores = [0.78, 0.71, 0.71, 0.65, 720]
    v3_scores = [0.88, 0.85, 0.91, 0.86, 600]
    hybrid_scores = [0.92, 0.89, 0.94, 0.90, 550]
    
    # Normalize latency for visualization (invert so lower is better/higher bar)
    max_latency = 1000
    v1_scores[4] = (max_latency - v1_scores[4]) / max_latency * 100
    v2_scores[4] = (max_latency - v2_scores[4]) / max_latency * 100
    v3_scores[4] = (max_latency - v3_scores[4]) / max_latency * 100
    hybrid_scores[4] = (max_latency - hybrid_scores[4]) / max_latency * 100
    
    x = np.arange(len(metrics))
    width = 0.18
    
    # Create bars with gradients
    bars1 = ax.bar(x - 1.5*width, v1_scores, width, label='v1 (Baseline)', 
                   color='#64748b', alpha=0.8, edgecolor='white', linewidth=0.5)
    bars2 = ax.bar(x - 0.5*width, v2_scores, width, label='v2 (7-slot Pipeline)', 
                   color=COLORS['traditional'], alpha=0.9, edgecolor='white', linewidth=0.5)
    bars3 = ax.bar(x + 0.5*width, v3_scores, width, label='v3 (Escalation Gate)', 
                   color=COLORS['hybrid'], alpha=0.9, edgecolor='white', linewidth=0.5)
    bars4 = ax.bar(x + 1.5*width, hybrid_scores, width, label='Hybrid (Current)', 
                   color=COLORS['accent'], alpha=1.0, edgecolor='white', linewidth=1.5)
    
    # Add value labels on bars
    def add_labels(bars, values, is_latency=False):
        for bar, val in zip(bars, values):
            height = bar.get_height()
            if is_latency and val == values[-1]:
                label = f'{int(1000 - val * 10)}'
            elif is_latency:
                label = f'{int(1000 - val * 10)}'
            else:
                label = f'{val:.2f}'
            ax.annotate(label,
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3),
                       textcoords="offset points",
                       ha='center', va='bottom',
                       fontsize=8, color='white', fontweight='bold')
    
    add_labels(bars1, [0.72, 0.65, 0.58, 0.52, 850])
    add_labels(bars2, [0.78, 0.71, 0.71, 0.65, 720])
    add_labels(bars3, [0.88, 0.85, 0.91, 0.86, 600])
    add_labels(bars4, [0.92, 0.89, 0.94, 0.90, 550])
    
    # Customize
    ax.set_ylabel('Score', fontsize=12, fontweight='bold', color=COLORS['text'])
    ax.set_title('Jev-RAG Benchmark Results', fontsize=20, fontweight='bold', 
                 color=COLORS['text'], pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=10, color=COLORS['text_muted'])
    ax.legend(loc='upper left', framealpha=0.9, facecolor=COLORS['bg_light'], 
              edgecolor=COLORS['border'], fontsize=10)
    ax.set_ylim(0, 105)
    ax.grid(axis='y', alpha=0.2, color=COLORS['border'])
    
    # Add subtitle
    ax.text(0.5, 1.02, 'Comparing pipeline versions across key metrics', 
            transform=ax.transAxes, ha='center', fontsize=12, 
            color=COLORS['text_muted'], style='italic')
    
    plt.tight_layout()
    plt.savefig('v3-results-chart.png', dpi=150, bbox_inches='tight', 
                facecolor=COLORS['bg'], edgecolor='none')
    plt.close()
    print("Created v3-results-chart.png")


def create_escalation_gate_diagram():
    """Create the escalation gate flow diagram."""
    fig, ax = plt.subplots(figsize=(14, 10), dpi=150)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 10)
    ax.set_facecolor(COLORS['bg'])
    ax.axis('off')
    
    def draw_box(ax, x, y, width, height, text, color, text_color='white', 
                 fontsize=10, fontweight='bold', alpha=0.9):
        """Draw a rounded box with text."""
        box = FancyBboxPatch((x - width/2, y - height/2), width, height,
                             boxstyle="round,pad=0.02,rounding_size=0.15",
                             facecolor=color, edgecolor='white', 
                             linewidth=1.5, alpha=alpha)
        ax.add_patch(box)
        ax.text(x, y, text, ha='center', va='center', fontsize=fontsize,
                color=text_color, fontweight=fontweight, wrap=True)
    
    def draw_diamond(ax, x, y, size, text, color):
        """Draw a diamond shape for decision."""
        diamond = plt.Polygon([(x, y+size), (x+size*1.2, y), 
                              (x, y-size), (x-size*1.2, y)], 
                             facecolor=color, edgecolor='white', linewidth=2)
        ax.add_patch(diamond)
        ax.text(x, y, text, ha='center', va='center', fontsize=9,
                color='white', fontweight='bold')
    
    def draw_arrow(ax, x1, y1, x2, y2, color='white', style='->', lw=2):
        """Draw an arrow between two points."""
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                   arrowprops=dict(arrowstyle=style, color=color, lw=lw))
    
    # Title
    ax.text(7, 9.5, 'Jev-RAG Escalation Gate', ha='center', fontsize=22, 
            fontweight='bold', color=COLORS['text'])
    ax.text(7, 9.0, 'Context Sufficiency Decision Flow', ha='center', fontsize=12, 
            color=COLORS['text_muted'], style='italic')
    
    # Input: Reranked Passages
    draw_box(ax, 2.5, 7.5, 3.5, 1.2, 'Reranked Passages\nAfter jev-score reranking', 
             COLORS['traditional'], fontsize=9)
    
    # Arrow to Score Features
    draw_arrow(ax, 2.5, 6.9, 2.5, 6.0)
    
    # Score Features
    draw_box(ax, 2.5, 5.3, 3.5, 1.0, 'Score Features\ntop_score · score_gap · coverage', 
             COLORS['accent'], fontsize=9)
    
    # Arrow to Decision
    draw_arrow(ax, 4.25, 4.8, 5.5, 4.0)
    
    # Decision Diamond
    draw_diamond(ax, 7, 3.5, 0.8, 'CONTEXT\nSUFFICIENT?', '#f59e0b')
    
    # YES path
    draw_arrow(ax, 8.2, 4.0, 9.5, 5.5, COLORS['hybrid'], lw=2.5)
    ax.text(8.8, 5.0, 'YES', fontsize=11, color=COLORS['hybrid'], 
            fontweight='bold', ha='center')
    
    # Sufficient Context box
    draw_box(ax, 11, 6.2, 2.5, 1.0, 'Context Sufficient\nRoute to qwen3.7-plus', 
             COLORS['hybrid'], fontsize=9)
    
    # NO path
    draw_arrow(ax, 8.2, 3.0, 9.5, 1.8, '#f59e0b', lw=2.5)
    ax.text(8.8, 2.2, 'NO', fontsize=11, color='#f59e0b', 
            fontweight='bold', ha='center')
    
    # Insufficient Context box
    draw_box(ax, 11, 1.2, 2.5, 1.0, 'Context Insufficient\nRoute to qwen3.6-plus', 
             '#f59e0b', fontsize=9)
    
    # Arrows to Model Router
    draw_arrow(ax, 12.25, 5.7, 12.25, 4.2, color='white')
    draw_arrow(ax, 12.25, 1.7, 12.25, 3.3, color='white')
    
    # Model Router
    draw_box(ax, 9.5, 3.5, 2.5, 0.9, 'Model Router', COLORS['cloud'], fontsize=10)
    
    # Arrow to Final Answer
    draw_arrow(ax, 8.25, 3.5, 5.5, 3.5, color='white')
    
    # Final Answer
    draw_box(ax, 3.5, 2.0, 3.0, 1.2, 'Final Answer\nCited + Groundedness Badge', 
             COLORS['hybrid_dark'], fontsize=10)
    
    # Threshold info box
    info_box = FancyBboxPatch((0.3, 0.2), 3.5, 1.3,
                              boxstyle="round,pad=0.02,rounding_size=0.1",
                              facecolor=COLORS['bg_light'], edgecolor=COLORS['border'], 
                              linewidth=1.5, alpha=0.9)
    ax.add_patch(info_box)
    ax.text(2.05, 1.2, 'Gate Thresholds', ha='center', fontsize=10, 
            fontweight='bold', color=COLORS['text'])
    ax.text(2.05, 0.9, 'score_threshold = 0.75', ha='center', fontsize=9, 
            color=COLORS['text_muted'])
    ax.text(2.05, 0.65, 'gap_threshold = 0.15', ha='center', fontsize=9, 
            color=COLORS['text_muted'])
    ax.text(2.05, 0.4, 'coverage_min = 0.60', ha='center', fontsize=9, 
            color=COLORS['text_muted'])
    
    # Legend
    legend_y = 0.8
    legend_items = [
        (COLORS['traditional'], 'Input'),
        (COLORS['accent'], 'Processing'),
        (COLORS['hybrid'], 'Success'),
        ('#f59e0b', 'Escalation'),
    ]
    
    for i, (color, label) in enumerate(legend_items):
        x_pos = 5.5 + i * 2
        rect = Rectangle((x_pos - 0.15, legend_y - 0.1), 0.3, 0.2, 
                         facecolor=color, edgecolor='white', linewidth=1)
        ax.add_patch(rect)
        ax.text(x_pos + 0.3, legend_y, label, fontsize=9, 
                color=COLORS['text_muted'], va='center')
    
    plt.tight_layout()
    plt.savefig('escalation-gate-v2.png', dpi=150, bbox_inches='tight',
                facecolor=COLORS['bg'], edgecolor='none')
    plt.close()
    print("Created escalation-gate-v2.png")


def create_architecture_diagram():
    """Create the v3 architecture diagram."""
    fig, ax = plt.subplots(figsize=(16, 9), dpi=150)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.set_facecolor(COLORS['bg'])
    ax.axis('off')
    
    def draw_box(ax, x, y, width, height, title, subtitle=None, color=COLORS['bg_light'],
                 text_color='white', fontsize_title=9, fontsize_sub=8):
        """Draw a box with title and optional subtitle."""
        box = FancyBboxPatch((x, y), width, height,
                             boxstyle="round,pad=0.02,rounding_size=0.1",
                             facecolor=color, edgecolor='white', 
                             linewidth=1.5, alpha=0.9)
        ax.add_patch(box)
        
        if subtitle:
            ax.text(x + width/2, y + height - 0.35, title, ha='center', va='top',
                   fontsize=fontsize_title, color=text_color, fontweight='bold')
            ax.text(x + width/2, y + height/2 + 0.1, subtitle, ha='center', va='center',
                   fontsize=fontsize_sub, color=COLORS['text_muted'])
        else:
            ax.text(x + width/2, y + height/2, title, ha='center', va='center',
                   fontsize=fontsize_title, color=text_color, fontweight='bold')
    
    def draw_arrow(ax, x1, y1, x2, y2, color='white', style='->', lw=1.5):
        """Draw an arrow."""
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                   arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                                  connectionstyle="arc3,rad=0"))
    
    # Title
    ax.text(8, 8.6, 'Jev-RAG v3 Architecture', ha='center', fontsize=20, 
            fontweight='bold', color=COLORS['text'])
    ax.text(8, 8.2, 'Local-First Hybrid RAG System', ha='center', fontsize=12, 
            color=COLORS['text_muted'], style='italic')
    
    # Document Ingestion (left column)
    draw_box(ax, 0.5, 5.5, 2.5, 2.5, 'Document Ingestion', 
             'Upload → markitdown\n→ Chunk → Embed', COLORS['bg_light'])
    
    # ChromaDB
    draw_box(ax, 0.5, 3.5, 2.5, 1.5, 'ChromaDB', 
             'Embedded vector store\n+ BM25 index', '#0c4a6e', '#7dd3fc')
    
    # Query Processing
    draw_box(ax, 3.5, 5.5, 2.5, 2.5, 'Query Processing',
             'User query → Embed\n→ Retrieve Top-K', COLORS['bg_light'])
    
    # Arrow from ingestion to query
    draw_arrow(ax, 3.0, 6.75, 3.5, 6.75)
    
    # Arrow from ChromaDB to query
    draw_arrow(ax, 3.0, 4.25, 3.5, 4.25)
    
    # Fork point
    fork_circle = Circle((6.75, 5.0), 0.25, facecolor='#475569', 
                          edgecolor='white', linewidth=2)
    ax.add_patch(fork_circle)
    ax.text(6.75, 5.0, 'F', ha='center', va='center', fontsize=10, fontweight='bold', color='white')
    
    # Arrow to fork
    draw_arrow(ax, 6.0, 5.5, 6.6, 5.0)
    
    # Traditional Pipeline (top)
    draw_box(ax, 7.5, 6.5, 2.8, 1.8, 'Top-4 Passages',
             'Direct to cloud LLM', COLORS['traditional'])
    
    draw_box(ax, 11.0, 6.5, 2.5, 1.8, 'Cloud LLM\nqwen3.7-plus',
             'System Two', '#1e1b4b', '#a5b4fc')
    
    draw_box(ax, 14.0, 6.5, 1.5, 1.8, 'Cited\nAnswer',
             'Fast path', COLORS['traditional'])
    
    # Arrows for traditional
    draw_arrow(ax, 10.3, 7.4, 11.0, 7.4, COLORS['traditional'])
    draw_arrow(ax, 13.5, 7.4, 14.0, 7.4, COLORS['traditional'])
    
    # Arrow from fork to traditional
    draw_arrow(ax, 7.0, 5.25, 7.5, 6.8, COLORS['traditional'])
    ax.text(7.2, 6.0, 'Simple queries', fontsize=8, color=COLORS['traditional'])
    
    # Hybrid Pipeline (bottom)
    draw_box(ax, 7.5, 1.0, 3.5, 3.5, 'Jev Engine (Local)',
             '0.8B GGUF on llama.cpp\nSystem One — Decision Model', '#064e3b', '#6ee7b7')
    
    # Steps inside Jev box
    steps = [
        ('1. Rerank Passages', 3.3),
        ('2. Escalation Gate', 2.6),
        ('3. Model Router', 1.9),
        ('4. Verify Groundedness', 1.2),
    ]
    for text, y_offset in steps:
        small_box = FancyBboxPatch((7.8, y_offset - 0.2), 2.9, 0.5,
                                    boxstyle="round,pad=0.02,rounding_size=0.05",
                                    facecolor='#047857', edgecolor='#059669', linewidth=1)
        ax.add_patch(small_box)
        ax.text(9.25, y_offset, text, ha='center', va='center', 
               fontsize=8, color='white', fontweight='bold')
    
    # Arrow from fork to hybrid
    draw_arrow(ax, 7.0, 4.75, 7.5, 3.0, COLORS['hybrid'])
    ax.text(7.2, 4.0, 'Complex queries', fontsize=8, color=COLORS['hybrid'])
    
    # Model Router in hybrid
    draw_box(ax, 11.5, 2.5, 2.0, 1.5, 'Model Router',
             'qwen3.7 vs\nqwen3.6-plus', COLORS['cloud'])
    
    draw_arrow(ax, 11.0, 2.75, 11.5, 2.75, COLORS['hybrid'])
    
    # Verified Answer
    draw_box(ax, 14.0, 2.0, 1.5, 2.0, 'Verified\nAnswer',
             'Citations +\nBadge', COLORS['hybrid'])
    
    draw_arrow(ax, 13.5, 3.0, 14.0, 3.0, COLORS['hybrid'])
    
    # Response section (rightmost)
    draw_box(ax, 11.0, 4.5, 4.5, 1.5, 'Response',
             'SSE Stream · Trace Panel · Citations · Groundedness Badge', 
             COLORS['bg_light'])
    
    # Arrows to response
    draw_arrow(ax, 15.5, 7.4, 13.55, 5.25, COLORS['traditional'])
    draw_arrow(ax, 15.5, 3.0, 13.55, 4.5, COLORS['hybrid'])
    
    # Legend at bottom
    legend_items = [
        (COLORS['traditional'], 'Traditional Pipeline'),
        (COLORS['hybrid'], 'Hybrid Pipeline (Jev-Style)'),
        (COLORS['cloud'], 'Cloud Component'),
        (COLORS['local'], 'Local Component'),
    ]
    
    for i, (color, label) in enumerate(legend_items):
        x_pos = 1.5 + i * 3.5
        rect = Rectangle((x_pos, 0.3), 0.4, 0.3, 
                         facecolor=color, edgecolor='white', linewidth=1)
        ax.add_patch(rect)
        ax.text(x_pos + 0.6, 0.45, label, fontsize=9, 
                color=COLORS['text_muted'], va='center')
    
    ax.text(15, 0.45, 'Everything except Cloud LLM runs locally', 
           fontsize=8, color=COLORS['text_muted'], ha='right', style='italic')
    
    plt.tight_layout()
    plt.savefig('v3-architecture-v2.png', dpi=150, bbox_inches='tight',
                facecolor=COLORS['bg'], edgecolor='none')
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

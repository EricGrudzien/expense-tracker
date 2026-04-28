import matplotlib.pyplot as plt
import numpy as np

# ── DATA ──────────────────────────────────────────────
months       = ['January', 'February', 'March']
cloud        = [34.2, 40.1, 48.9]
saas         = [28.7, 32.4, 38.2]
pro_services = [15.3, 17.8, 19.4]
hardware     = [11.2, 10.9, 12.2]
total        = [89.4, 101.2, 118.7]

# ── COLORS ────────────────────────────────────────────
colors = {
    'cloud'    : '#4A90D9',  # Blue
    'saas'     : '#7B68EE',  # Purple
    'pro'      : '#50C878',  # Green
    'hardware' : '#FF7F50',  # Orange
    'total'    : '#FF4757',  # Red
}

# ══════════════════════════════════════════════════════
# CHART 1 — GROUPED BAR CHART
# ══════════════════════════════════════════════════════
fig1, ax1 = plt.subplots(figsize=(12, 7))

x     = np.arange(len(months))
width = 0.2  # width of each bar

# Plot each product line as a group
bars1 = ax1.bar(x - 1.5*width, cloud,        width, label='Cloud Services', color=colors['cloud'],    edgecolor='white', linewidth=0.8)
bars2 = ax1.bar(x - 0.5*width, saas,         width, label='SaaS Platform',  color=colors['saas'],     edgecolor='white', linewidth=0.8)
bars3 = ax1.bar(x + 0.5*width, pro_services, width, label='Pro Services',   color=colors['pro'],      edgecolor='white', linewidth=0.8)
bars4 = ax1.bar(x + 1.5*width, hardware,     width, label='Hardware',       color=colors['hardware'], edgecolor='white', linewidth=0.8)

# Add value labels on top of each bar
def add_labels(bars):
    for bar in bars:
        height = bar.get_height()
        ax1.annotate(f'${height}M',
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 4),
                     textcoords="offset points",
                     ha='center', va='bottom',
                     fontsize=8, fontweight='bold')

add_labels(bars1)
add_labels(bars2)
add_labels(bars3)
add_labels(bars4)

# Formatting
ax1.set_title('NovaTech Solutions — Q1 2025\nRevenue by Product Line',
              fontsize=16, fontweight='bold', pad=20)
ax1.set_ylabel('Revenue ($ Millions)', fontsize=12)
ax1.set_xlabel('Month', fontsize=12)
ax1.set_xticks(x)
ax1.set_xticklabels(months, fontsize=11)
ax1.set_ylim(0, 65)
ax1.yaxis.grid(True, linestyle='--', alpha=0.7)
ax1.set_axisbelow(True)
ax1.legend(loc='upper left', fontsize=10)
ax1.set_facecolor('#F8F9FA')
fig1.patch.set_facecolor('#FFFFFF')

# Add a subtitle
fig1.text(0.5, 0.01, 'Ticker: NVTC  |  Fiscal Q1 ended March 31, 2025',
          ha='center', fontsize=9, color='gray')

plt.tight_layout()
plt.savefig('novatech_bar_chart.png', dpi=150, bbox_inches='tight')
plt.show()
print("✅ Bar chart saved as 'novatech_bar_chart.png'")


# ══════════════════════════════════════════════════════
# CHART 2 — LINE CHART (Trends Over Q1)
# ══════════════════════════════════════════════════════
fig2, ax2 = plt.subplots(figsize=(12, 7))

# Plot each line with markers
ax2.plot(months, cloud,        marker='o', linewidth=2.5, markersize=8, label='Cloud Services', color=colors['cloud'])
ax2.plot(months, saas,         marker='s', linewidth=2.5, markersize=8, label='SaaS Platform',  color=colors['saas'])
ax2.plot(months, pro_services, marker='^', linewidth=2.5, markersize=8, label='Pro Services',   color=colors['pro'])
ax2.plot(months, hardware,     marker='D', linewidth=2.5, markersize=8, label='Hardware',       color=colors['hardware'])
ax2.plot(months, total,        marker='*', linewidth=3.0, markersize=12, label='Total Revenue', color=colors['total'],
         linestyle='--')

# Add data point labels
all_lines = [
    (cloud,        colors['cloud']),
    (saas,         colors['saas']),
    (pro_services, colors['pro']),
    (hardware,     colors['hardware']),
    (total,        colors['total']),
]

for data, color in all_lines:
    for i, (month, value) in enumerate(zip(months, data)):
        ax2.annotate(f'${value}M',
                     xy=(i, value),
                     xytext=(0, 10),
                     textcoords='offset points',
                     ha='center', fontsize=8,
                     fontweight='bold', color=color)

# Add shaded area under Total Revenue line
ax2.fill_between(months, total, alpha=0.08, color=colors['total'])

# Formatting
ax2.set_title('NovaTech Solutions — Q1 2025\nRevenue Trends by Product Line',
              fontsize=16, fontweight='bold', pad=20)
ax2.set_ylabel('Revenue ($ Millions)', fontsize=12)
ax2.set_xlabel('Month', fontsize=12)
ax2.set_ylim(0, 140)
ax2.yaxis.grid(True, linestyle='--', alpha=0.7)
ax2.set_axisbelow(True)
ax2.legend(loc='upper left', fontsize=10)
ax2.set_facecolor('#F8F9FA')
fig2.patch.set_facecolor('#FFFFFF')

# Add a subtitle
fig2.text(0.5, 0.01, 'Ticker: NVTC  |  Fiscal Q1 ended March 31, 2025',
          ha='center', fontsize=9, color='gray')

plt.tight_layout()
plt.savefig('novatech_line_chart.png', dpi=150, bbox_inches='tight')
plt.show()
print("✅ Line chart saved as 'novatech_line_chart.png'")


# ══════════════════════════════════════════════════════
# CHART 3 — BONUS: COMBO CHART (Bar + Line Together)
# ══════════════════════════════════════════════════════
fig3, ax3 = plt.subplots(figsize=(12, 7))

x     = np.arange(len(months))
width = 0.5

# Stacked bars
ax3.bar(x, cloud,        width, label='Cloud Services', color=colors['cloud'])
ax3.bar(x, saas,         width, label='SaaS Platform',  color=colors['saas'],     bottom=cloud)
ax3.bar(x, pro_services, width, label='Pro Services',   color=colors['pro'],
        bottom=[c+s for c,s in zip(cloud, saas)])
ax3.bar(x, hardware,     width, label='Hardware',       color=colors['hardware'],
        bottom=[c+s+p for c,s,p in zip(cloud, saas, pro_services)])

# Overlay total revenue as a line
ax3.plot(x, total, marker='o', linewidth=3, markersize=10,
         color=colors['total'], label='Total Revenue', zorder=5)

# Label total line points
for i, val in enumerate(total):
    ax3.annotate(f'${val}M',
                 xy=(i, val),
                 xytext=(0, 12),
                 textcoords='offset points',
                 ha='center', fontsize=10,
                 fontweight='bold', color=colors['total'])

# Formatting
ax3.set_title('NovaTech Solutions — Q1 2025\nStacked Revenue + Total Trend Line',
              fontsize=16, fontweight='bold', pad=20)
ax3.set_ylabel('Revenue ($ Millions)', fontsize=12)
ax3.set_xlabel('Month', fontsize=12)
ax3.set_xticks(x)
ax3.set_xticklabels(months, fontsize=11)
ax3.set_ylim(0, 140)
ax3.yaxis.grid(True, linestyle='--', alpha=0.7)
ax3.set_axisbelow(True)
ax3.legend(loc='upper left', fontsize=10)
ax3.set_facecolor('#F8F9FA')
fig3.patch.set_facecolor('#FFFFFF')

fig3.text(0.5, 0.01, 'Ticker: NVTC  |  Fiscal Q1 ended March 31, 2025',
          ha='center', fontsize=9, color='gray')

plt.tight_layout()
plt.savefig('novatech_combo_chart.png', dpi=150, bbox_inches='tight')
plt.show()
print("✅ Combo chart saved as 'novatech_combo_chart.png'")
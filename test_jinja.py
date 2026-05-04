from jinja2 import Template

template = Template('''
<div class="flex-1">
    {% if question.content and question.content.strip() %}
    <h1 class="font-headline-md text-headline-md text-on-surface whitespace-pre-line">
        {{ question.content }}
    </h1>

    <!-- Eger content icinde Shorts linki varsa, iframe ile goster -->
    {% if 'youtube.com/shorts/' in question.content %}
        {% set parts = question.content.split('youtube.com/shorts/') %}
        {% if parts|length > 1 %}
            {% set video_id = parts[1].split()[0] %}
            <div class="mt-6 rounded-2xl overflow-hidden border border-slate-200 premium-shadow" style="width: 315px; height: 560px;">
                <iframe width="100%" height="100%" 
                    src="https://www.youtube.com/embed/{{ video_id }}?rel=0" 
                    title="YouTube video player" frameborder="0" 
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                    allowfullscreen>
                </iframe>
            </div>
        {% endif %}
    {% endif %}
    {% endif %}
</div>
''')

class Q:
    def __init__(self):
        self.content = 'YouTube Shorts Sorusunu İzle: Çıkmış Problem Soru Çözümü | 1 DK 1 NET\nVideo Linki: https://www.youtube.com/shorts/ZBb_312mVh4'

print(template.render(question=Q()))

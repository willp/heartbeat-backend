from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .models import HeartbeatEntry

@require_GET
def heartbeat_list_json(request):
    """
    Returns all heartbeat records directly from the database as JSON.
    Preserves NULL values as null. Only accepts GET requests.
    """
    # .values() retrieves a list of dictionaries containing raw database fields
    data = list(HeartbeatEntry.objects.values())
    
    # safe=False is required because the outer JSON structure is an Array [], not an Object {}
    # json_dumps_params={'indent': 4} pretty-prints it for easier debugging in your browser
    return JsonResponse(data, safe=False, json_dumps_params={'indent': 4})
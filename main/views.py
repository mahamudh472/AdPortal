from rest_framework.response import Response
from rest_framework import generics, permissions, status
from .serializers import CreateAdSerializer

class CreateAdAPIView(generics.GenericAPIView):
	permission_classes = [permissions.IsAuthenticated]
	
	def post(self, request, *args, **kwargs):
		serializer = CreateAdSerializer(data=request.data)

		if serializer.is_valid(raise_exception=True):
			print(serializer.validated_data)
			return Response(serializer.data)
		else:
			return Response({'error': 'Error creating Ad'}, status=status.HTTP_400_BAD_REQUEST)
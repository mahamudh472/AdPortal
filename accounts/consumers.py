import json
from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationConsumer(AsyncWebsocketConsumer):
	async def connect(self) -> None:
		await self.accept()

	async def disconnect(self, code: int) -> None:
		pass

	async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
		if text_data != None:
			data = json.loads(text_data)

			message = data['message']

			await self.channel_layer.group_send(
				'notification_group',
				{
					'type': 'send_notification',
					'message': 'message'
				}
			)
	async def send_notification(self, event):
		message = event['message']
		await self.send(text_data=json.dumps({'message': message}))

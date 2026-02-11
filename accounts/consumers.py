import json
from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self) -> None:
        user = self.scope['user']
        print(f"User {user} connected to WebSocket")
        if user and user.is_anonymous:
            await self.close()
            return
        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, code: int) -> None:
        await self.channel_layer.group_discard(self.group_name, self.channel_name)


    # async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
    #     if text_data != None:
    #         data = json.loads(text_data)
    #
    #         message = data['message']
    #
    #         await self.channel_layer.group_send(
    #             'notification_group',
    #             {
    #                 'type': 'send_notification',
    #                 'message': 'message'
    #             }
    #         )
    async def send_notification(self, event):
            await self.send(text_data=json.dumps({
                'type': 'notification',
                'data': event['data']
            }))

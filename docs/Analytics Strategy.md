

User connects their Ad accounts and they can sync all of their ads in our platform. They will also be able to see their analytics here. We need to get each day analytics for each campaign to properly show them in out platform and manage them. The issue will occure if the user have old campaigns like 3-5 years old and if we want to store every day data it will fill the db with just only one user. So we shouldn't do this. Instead,

- First fetch last 30 days data for each campaign.
- We will fetch previous data if the user want's to see previous data. But not every day data. Instead we will get aggregate values and show that to the user. We need decrease the load in our db.

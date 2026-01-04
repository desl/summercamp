# Summer Camp Organization Tool

Organizing summer camp for multiple kids is challenging. I would like an app to help keep it organized from beginning to end. Planning for summer camp starts in the beginning of January.

The purpose of the app is to

* Track all of the ideas for camp sessions for different weeks for each kid  
* Keep track of what is booked, for each week. Once a camp is booked for a kid in a week, the other “ideas” for that week should be grayed out or optionally not displayed.  
* Understand what weeks are in the summer. Keep track of dates that school ends and starts  
* Block off weeks for family trips when camps are not needed.

The app should enroll the family. Who are parents and who are kids

For each kid the app should take a “last day of school” and “first day of school”. The first week of summer begins the Monday following the last day of school. If the days are different the first week of summer is first week any kid has no school on any weekday.

Once the kids/school/weeks are determined, it’ time to start putting in camps. Each week should allow the user to submit ideas and set an order of preference. Some kind of warning indicator should be given for situations where the primary choice has reservations that open after reservations open for a secondary choice. When an “idea’ becomes registered it should be locked in. The other camps should be hidden but kept around as backup options.

Trips have

* Start Dates  
* End Dates  
* Names

Parents have

* Names  
* Email addresses  
* Calendars (assume google calendars)

Kids have

* Names  
* Birthdays  
* Grades  
* Friends (just a name)

Camps Have

* Names  
* Sessions  
* Contact information  
  * Website  
  * Phone number  
  * Email Address  
  * 

Sessions Have

* Age Ranges  
* Weeks  
  * Some sessions may be more than 1 week long. 2 week long sessions are common.  
* Holidays (For example, some camps are closed on Juneteenth and/or the 4th of July).  
* Start Time  
* End Time  
* Drop off window  
* Pick Up Window  
* URL for the session (may or may not have this)  
* Friends who will be joining them

Weeks Have

* Start Dates  
* End Dates

Things the app should have

* Camp URL  
* Week URL  
* Which “session” is good for which kid.  
* Start and End times of camp. Limits for drop off and pick up.  
* Keep options for early care and late care (and their costs)  
* Be able to present options for each week.  
* Understand that things are “ideas” “booked” and “preferred”  
* Camps have signups that open on particular days and times. Those should be tracked. Place calendar entries to do signups.  
* Cost  
* Maybe: review url for session and confirm that kid is eligible by grade and/or age at time of camp.  
* Tag weeks or sessions of camps that kids friends are doing.  
* Tag when we can carpool with friends  
* Camp

Things the app should do

* Once the camp is “booked” it should be added to a google calendar. This will be a different calendar than the “registration” times go into.

Nice to haves

* Notify when booking is opening a few minutes ahead of time via google calendar notifications.  
* Summary data of total cost of camp  
* Ability to find receipts in email

# Technical

The app will have a small number of users, probably one or two. It seems like a serverless architecture would be ideal. That said if it’s useful I would like to make it available to others as a business.

This should be a lightweight app written in python. Flask is probably the best framework to use.

The app will have to handle identity and authentication. Federating that from Google is probably the best way to do it.

The app will need to be used from a mobile browsers as well as a desktop browser. This app is replacing a complicated spreadsheet so it’s expected that it will need to use a fair amount of screen real estate

Code should be written assuming it will be maintained by a beginning software engineer and commented with the “why” for an approach. Understandable code is valued more than performance or clever solutions.

The app we build will also include all the steps needed to deploy. We will be able to deploy to “test” and “production” environments.

We will use a revision control system. Let’s use github.

We will not run this locally on the laptop. We will start by deploying to dev and build “hello world” there first. We will build auth/id next, then make the app. 
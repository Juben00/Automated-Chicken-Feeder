# 🐔 How the Chicken Feeder System Works

## The Players (Who's Involved?)

Think of this system like a team working together:

| Player | What It Is | Job |
|--------|-----------|-----|
| **Flask Server** 🖥️ | A computer (your laptop/PC) | The "Brain" - makes decisions |
| **Raspberry Pi** 🍓 | A tiny computer near the chicken coop | The "Helper" - does the physical work |
| **Camera** 📷 | Attached to the Pi | Takes photos of the food tray |
| **Servo Motor** ⚙️ | A spinning motor | Opens/closes the food door |
| **You** 👤 | The user | Sets up feeding schedules on a website |

---

## Story Time: A Day in the Life of the Chicken Feeder 🐔

### Morning Setup (You Create a Schedule)

```
    👤 You
     │
     │  "Feed my chickens 50 grams at 8:00 AM"
     ▼
   ┌─────────────────┐
   │  📱 Website     │
   │  (Flask Server) │
   └────────┬────────┘
            │
            ▼
   📝 Saves to database:
      "Schedule #1: 50g at 8:00 AM"
```

**In simple words:** You go to a website and say "Please feed my chickens 50 grams of food at 8:00 AM tomorrow."

---

### 8:00 AM - Feeding Time! ⏰

Here's what happens step by step:

#### Step 1: Wake Up Call 📞

```
   ┌─────────────────┐                    ┌─────────────────┐
   │  Flask Server   │                    │  Raspberry Pi   │
   │  (The Brain)    │                    │  (The Helper)   │
   └────────┬────────┘                    └────────┬────────┘
            │                                      │
            │  "Hey Pi! It's 8:00 AM!"             │
            │  "Time to feed the chickens!"        │
            │  "Here's schedule #1"                │
            │ ────────────────────────────────────>│
            │                                      │
```

**In simple words:** The brain (Flask) looks at the clock. "Oh! It's 8:00 AM! Time to wake up my helper!"

---

#### Step 2: Take a Photo 📸

```
            │                                      │
            │                                      │  "OK! Let me check
            │                                      │   the food tray first!"
            │                                      │
            │                              ┌───────┴───────┐
            │                              │    📷         │
            │                              │  *CLICK*      │
            │                              │  Takes photo  │
            │                              └───────┬───────┘
            │                                      │
```

**In simple words:** Before giving new food, the Pi takes a photo of the food tray. "Let me see how much food is still there!"

---

#### Step 3: Send Photo to the Brain 🖼️

```
            │                                      │
            │      "Here's a photo of the tray!"   │
            │      "My name is pi_kleo"            │
            │      "My password is ABC123"         │
            │<─────────────────────────────────────│
            │         📷 [PHOTO]                   │
            │                                      │
```

**In simple words:** The Pi sends the photo to the brain and says "Here! Look at this photo. By the way, I'm your trusted helper pi_kleo, and here's my secret password so you know it's really me!"

---

#### Step 4: Brain Counts the Food 🧠

```
   ┌─────────────────┐
   │  Flask Server   │
   │                 │
   │  🔍 Looking at  │
   │     photo...    │
   │                 │
   │  "I see 100     │
   │   pellets!"     │
   │                 │
   │  "That's about  │
   │   20 grams of   │
   │   food already  │
   │   in the tray"  │
   │                 │
   │  "Schedule says │
   │   50 grams..."  │
   │                 │
   │  "50 - 20 = 30" │
   │                 │
   │  "Need to add   │
   │   30 grams!"    │
   └────────┬────────┘
            │
```

**In simple words:** The brain is very smart! It uses AI (like a robot brain) to count how many food pellets are in the photo. Then it does math:
- "The schedule says 50 grams"
- "There's already 20 grams in the tray"
- "So I only need to add 30 more grams!"

---

#### Step 5: Tell the Pi How Much to Dispense 📢

```
            │                                      │
            │   "Add 30 grams of food!"            │
            │ ────────────────────────────────────>│
            │                                      │
            │                                      │  "Got it! 30 grams!"
            │                                      │
```

**In simple words:** The brain tells the helper: "Please add 30 grams of food to the tray!"

---

#### Step 6: Dispense the Food! ⚙️

```
            │                                      │
            │                              ┌───────┴───────┐
            │                              │    ⚙️ Servo   │
            │                              │               │
            │                              │  30g ÷ 5g =   │
            │                              │  6 movements  │
            │                              │               │
            │                              │  *WHIRR*      │
            │                              │  ↻ 0° (5g)    │
            │                              │  ↺ 180° (5g)  │
            │                              │  ↻ 0° (5g)    │
            │                              │  ↺ 180° (5g)  │
            │                              │  ↻ 0° (5g)    │
            │                              │  ↺ 180° (5g)  │
            │                              │               │
            │                              │  Total: 30g!  │
            │                              └───────┬───────┘
            │                                      │
```

**In simple words:** The servo motor is like a little door. Each time it moves, it drops 5 grams of food. For 30 grams, it moves 6 times!

---

#### Step 7: Report Back 📋

```
            │                                      │
            │   "Done! I dispensed 30 grams!"      │
            │<─────────────────────────────────────│
            │                                      │
   ┌────────┴────────┐
   │  Flask Server   │
   │                 │
   │  ✅ Success!    │
   │                 │
   │  📝 Save to log │
   │  📧 Send email  │
   │     to owner    │
   └─────────────────┘
```

**In simple words:** The Pi tells the brain "All done! I gave the chickens 30 grams of food!" The brain writes this down in a diary and sends you an email saying "Your chickens have been fed!"

---

## The Secret Handshake 🤝 (Authentication)

How does the Flask server know the Pi is not a stranger?

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   When you first set up the system, you register the Pi:   │
│                                                             │
│   Flask Server's Database:                                  │
│   ┌─────────────────────────────────────────────────────┐  │
│   │  Device: "pi_kleo"                                  │  │
│   │  Secret Password: "8ysMBxU6wqJIr_V12ZLwyGD..."      │  │
│   │  Owner: You                                          │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
│   Raspberry Pi's config.json:                               │
│   ┌─────────────────────────────────────────────────────┐  │
│   │  "device_id": "pi_kleo"                             │  │
│   │  "user_token": "8ysMBxU6wqJIr_V12ZLwyGD..."         │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
│   They must MATCH! Like a secret handshake only they know!  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Manual Feeding (When You Want to Feed NOW) 🖱️

```
    👤 You click "Dispense 50g" on the website
         │
         ▼
   ┌─────────────────┐          ┌─────────────────┐
   │  Flask Server   │          │  Raspberry Pi   │
   │                 │          │                 │
   │  "User wants    │          │                 │
   │   50g NOW!"     │          │                 │
   │                 │─────────>│  ⚙️ *WHIRR*     │
   │  POST /dispense │          │  Dispense 50g   │
   │  {amount: 50}   │          │                 │
   │                 │<─────────│  "Done!"        │
   └─────────────────┘          └─────────────────┘
```

**In simple words:** You can also press a button on the website that says "Feed now!" and the brain immediately tells the Pi to drop food.

---

## Summary Picture 🎨

```
                           ☁️ INTERNET ☁️
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       │                       ▼
   ┌─────────┐                  │                 ┌──────────┐
   │ 📱 You  │                  │                 │ 🍓 Pi    │
   │ Website │                  │                 │ + 📷 + ⚙️│
   └────┬────┘                  │                 └────┬─────┘
        │                       │                      │
        │    ┌──────────────────┴──────────────────┐   │
        └───>│          🖥️ Flask Server            │<──┘
             │                                     │
             │  • Stores schedules                 │
             │  • Counts pellets with AI           │
             │  • Calculates how much to dispense  │
             │  • Keeps logs                       │
             │  • Sends email notifications        │
             └─────────────────────────────────────┘
                                │
                                ▼
                         🐔🐔🐔 Happy Chickens! 🐔🐔🐔
```

---

## Why Is This Smart? 🧠

1. **No Wasted Food** - It checks how much food is already there before adding more
2. **Remote Control** - You can feed your chickens from anywhere with internet
3. **Automatic** - Set it once, and it feeds your chickens every day at the same time
4. **You Get Notifications** - Email tells you when feeding happens
5. **Keeps Records** - You can see history of all feedings

That's how your smart chicken feeder works! 🐔✨
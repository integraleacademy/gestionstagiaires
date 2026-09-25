from PIL import ImageDraw
S=2
GOLD="#F2C461"
def box(d,b,fill,outline=None,r=0,width=1):
 b=tuple(round(x*S) for x in b)
 if r:d.rounded_rectangle(b,r*S,fill,outline,width*S)
 else:d.rectangle(b,fill,outline,width*S)
def line(d,pts,color=GOLD,width=3):d.line([(round(x*S),round(y*S)) for x,y in pts],fill=color,width=width*S,joint='curve')
def circle(d,x,y,r,fill=None,outline=None,width=2):d.ellipse(((x-r)*S,(y-r)*S,(x+r)*S,(y+r)*S),fill,outline,width*S)
def icon(d,kind,cx,cy,scale=1,color=GOLD):
 # Exact conceptual symbols rather than photo-like illustrations.
 def L(points,w=5):line(d,[(cx+x*scale,cy+y*scale) for x,y in points],color,w)
 def B(b,r=8,fill=None):box(d,tuple((cx if i%2==0 else cy)+v*scale for i,v in enumerate(b)),fill,color,r,4)
 def C(x,y,r):circle(d,cx+x*scale,cy+y*scale,r*scale,outline=color,width=4)
 if kind=='book':
  L([(-150,-120),(-15,-110),(0,-90),(15,-110),(150,-120),(150,120),(20,126),(0,143),(-20,126),(-150,120),(-150,-120)])
  L([(0,-90),(0,143)],3)
  for y in [-55,-5,45]:L([(-116,y),(-42,y+6)],3);L([(40,y+6),(118,y)],3)
 elif kind=='badge':
  B((-125,-160,125,175),18);B((-43,-182,43,-140),8)
  C(0,-60,34);L([(-65,40),(-60,9),(-35,-7),(35,-7),(60,9),(65,40)])
  L([(-80,85),(80,85)],3);L([(-50,118),(50,118)],3)
 elif kind=='balance':
  L([(0,-160),(0,155)]);L([(-160,-80),(160,-80)]);L([(-80,156),(80,156)])
  C(0,-95,15)
  for x in [-115,115]:
   L([(x,-80),(x-54,38),(x+54,38),(x,-80)],3)
   L([(x-54,38),(x-35,65),(x+35,65),(x+54,38)],4)
 elif kind=='building':
  B((-132,-157,132,161),5);L([(-175,162),(175,162)]);B((-28,72,28,160),2)
  for x in [-81,0,81]:
   for y in [-95,-28]:B((x-14,y-16,x+14,y+16),2)
 elif kind=='shield':
  L([(0,-181),(143,-112),(132,47),(89,113),(0,179),(-89,113),(-132,47),(-143,-112),(0,-181)])
  L([(-64,-4),(-10,49),(79,-57)],8)
 elif kind=='clipboard':
  B((-125,-148,125,178),14);B((-48,-175,48,-125),8)
  for y in [-67,6,79]:L([(-79,y),(-65,y+13),(-42,y-14)],4);L([(-13,y),(79,y)],3)
 elif kind=='phone':
  B((-102,-167,102,180),24);L([(-35,-130),(35,-130)],3);C(0,140,8)
  L([(-61,0),(61,0)],7);L([(0,-61),(0,61)],7)
 elif kind=='lock':
  B((-133,-28,133,173),20)
  L([(-77,-30),(-77,-111),(-54,-154),(0,-174),(54,-154),(77,-111),(77,-30)],8)
  C(0,48,20);L([(0,70),(0,112)],7)
 elif kind=='screen':
  B((-180,-132,180,88),12);L([(-180,51),(180,51)],3);L([(0,88),(0,155)]);L([(-74,157),(74,157)])
  L([(-60,-66),(-92,-36),(-60,-6)],5);L([(60,-66),(92,-36),(60,-6)],5);L([(13,-80),(-13,8)],5)
 elif kind=='court':
  L([(-180,-92),(0,-190),(180,-92),(-180,-92)])
  for x in [-120,-40,40,120]:L([(x,-66),(x,119)],10)
  L([(-167,133),(167,133)]);L([(-190,165),(190,165)])


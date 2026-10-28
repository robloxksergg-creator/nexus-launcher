/* Shared CSS 3D cuboid renderer. No remote requests or account credentials. */
(() => {
  let profile=null, texture=null, generation=0, modelOverride=null;
  const pose={yaw:-25,zoom:8};
  const wrapped=angle=>((angle+180)%360+360)%360-180;
  const viewers=new Set();
  function cuboid(parent,x,y,z,w,h,d,uv,overlay=false){
    const part=document.createElement('div');part.className='skin-part';
    part.style.transform=`translate3d(${x}px,${y}px,${z}px)`;
    const faces=[['front',w,h,`translateZ(${d/2}px)`,uv[0]],['back',w,h,`rotateY(180deg) translateZ(${d/2}px)`,uv[1]],['left',d,h,`rotateY(-90deg) translateZ(${w/2}px)`,uv[2]],['right',d,h,`rotateY(90deg) translateZ(${w/2}px)`,uv[3]],['top',w,d,`rotateX(90deg) translateZ(${h/2}px)`,uv[4]],['bottom',w,d,`rotateX(-90deg) translateZ(${h/2}px)`,uv[5]]];
    faces.forEach(([name,fw,fh,transform,crop])=>{
      const face=document.createElement('canvas');face.className='skin-face skin-'+name;
      // Pre-rasterize texels: 3D compositor filtering of an 8px canvas blurs edges.
      const density=16;
      face.width=Math.ceil(fw*density);face.height=Math.ceil(fh*density);face.style.width=fw+'px';face.style.height=fh+'px';
      face.style.left=-fw/2+'px';face.style.top=-fh/2+'px';face.style.transform=transform;
      const ctx=face.getContext('2d');ctx.scale(density,density);ctx.imageSmoothingEnabled=false;
      if(!overlay){ctx.fillStyle={front:'#aaa',back:'#777',left:'#888',right:'#999',top:'#ccc',bottom:'#666'}[name];ctx.fillRect(0,0,fw,fh);}
      if(texture&&crop)ctx.drawImage(texture,...crop,0,0,fw,fh);
      part.append(face);
    });parent.append(part);
  }
  function boxUV(u,v,w,h,d){return [[u+d,v+d,w,h],[u+d+w+d,v+d,w,h],[u,v+d,d,h],[u+d+w,v+d,d,h],[u+d,v,w,d],[u+d+w,v,w,d]];}
  function draw(view){
    view.model.replaceChildren();const slim=(modelOverride??profile?.model)==='slim',arm=slim?3:4;
    if(view.arms)for(const input of view.arms)input.checked=input.value===(slim?'slim':'classic');
    cuboid(view.model,0,-12,0,8,8,8,boxUV(0,0,8,8,8));
    if(texture)cuboid(view.model,0,-12,0,8.5,8.5,8.5,boxUV(32,0,8,8,8),true);
    if(view.headOnly)return;
    cuboid(view.model,0,-2,0,8,12,4,boxUV(16,16,8,12,4));
    cuboid(view.model,-4-arm/2,-2,0,arm,12,4,boxUV(40,16,arm,12,4));
    cuboid(view.model,4+arm/2,-2,0,arm,12,4,texture?.height===32?boxUV(40,16,arm,12,4):boxUV(32,48,arm,12,4));
    cuboid(view.model,-2,10,0,4,12,4,boxUV(0,16,4,12,4));
    cuboid(view.model,2,10,0,4,12,4,texture?.height===32?boxUV(0,16,4,12,4):boxUV(16,48,4,12,4));
    if(texture?.height===64){
      cuboid(view.model,0,-2,0,8.25,12.25,4.25,boxUV(16,32,8,12,4),true);
      cuboid(view.model,-4-arm/2,-2,0,arm+.25,12.25,4.25,boxUV(40,32,arm,12,4),true);
      cuboid(view.model,4+arm/2,-2,0,arm+.25,12.25,4.25,boxUV(48,48,arm,12,4),true);
      cuboid(view.model,-2,10,0,4.25,12.25,4.25,boxUV(0,32,4,12,4),true);
      cuboid(view.model,2,10,0,4.25,12.25,4.25,boxUV(0,48,4,12,4),true);
    }
    view.status.textContent=(texture?'Скин профиля':'Скин отсутствует — серая 3D-модель')+' · '+(slim?'Тонкие руки · 3 px':'Стандартные руки · 4 px');
  }
  function mount(target){
    const card=document.createElement('section');card.className='skin-preview';card.setAttribute('aria-label','3D-модель Minecraft');
    const title=document.createElement('h3');title.textContent='Твой персонаж';
    const stage=document.createElement('div');stage.className='skin-stage';
    const model=document.createElement('div');model.className='skin-model';stage.append(model);
    const status=document.createElement('p');status.setAttribute('role','status');
    const turn=document.createElement('input');turn.type='range';turn.min=-180;turn.max=180;turn.value=wrapped(pose.yaw);turn.setAttribute('aria-label','Поворот персонажа');
    const zoom=document.createElement('input');zoom.type='range';zoom.min=5;zoom.max=10;zoom.value=pose.zoom;zoom.setAttribute('aria-label','Масштаб персонажа');
    const update=()=>{turn.value=wrapped(pose.yaw);turn.setAttribute('aria-valuetext',Math.round(wrapped(pose.yaw))+' градусов');model.style.transform=`rotateX(-8deg) rotateY(${pose.yaw}deg) scale3d(${pose.zoom},${pose.zoom},${pose.zoom})`;};
    turn.oninput=()=>{pose.yaw=+turn.value;update();};zoom.oninput=()=>{pose.zoom=+zoom.value;update();};update();
    turn.onkeydown=e=>{
      const step={ArrowLeft:-5,ArrowDown:-5,ArrowRight:5,ArrowUp:5,PageDown:-45,PageUp:45}[e.key];
      if(step!==undefined){e.preventDefault();pose.yaw+=step;update();}
    };
    let last=null;
    stage.onpointerdown=e=>{if(e.button!==0)return;last=e.clientX;stage.setPointerCapture(e.pointerId);};
    stage.onpointermove=e=>{if(last===null)return;pose.yaw+=e.clientX-last;last=e.clientX;update();};
    stage.onpointerup=stage.onpointercancel=stage.onlostpointercapture=()=>{last=null;};
    const rotation=document.createElement('label');rotation.textContent='Поворот';rotation.append(turn);
    const scaling=document.createElement('label');scaling.textContent='Масштаб';scaling.append(zoom);
    const options=document.createElement('fieldset');options.className='skin-arm-options';
    const legend=document.createElement('legend');legend.textContent='Тип рук';options.append(legend);
    const arms=[];
    for(const [value,text] of [['classic','Стандартные · 4 px'],['slim','Тонкие · 3 px']]){
      const label=document.createElement('label');const input=document.createElement('input');input.type='radio';input.name='skin-preview-arm-model';input.value=value;
      input.onchange=()=>{if(input.checked){modelOverride=value;refresh();}};
      label.append(input,document.createTextNode(text));options.append(label);arms.push(input);
    }
    card.append(title,stage,status,rotation,scaling,options);target.append(card);
    const view={model,status,arms};viewers.add(view);draw(view);
  }
  function refresh(){for(const view of viewers){if(!view.model.isConnected){viewers.delete(view);continue;}draw(view);}}
  window.NexusSkin=Object.freeze({mount,setProfile(value){
    profile=value;modelOverride=null;texture=null;const current=++generation;refresh();
    if(!value?.png)return;
    const img=new Image();img.onload=()=>{if(current!==generation)return;if(img.width===64&&[32,64].includes(img.height)){texture=img;refresh();}};
    img.src='data:image/png;base64,'+value.png;
  }});
  if(typeof showProfileSpace==='undefined')return;
  const previous=showProfileSpace;
  showProfileSpace=tab=>{
    previous(tab);const target=profileSpace.querySelector('.profile-summary');if(target){target.replaceChildren();mount(target);}
    const avatar=profileSpace.querySelector('.profile-avatar-placeholder');
    if(avatar){avatar.replaceChildren();avatar.classList.add('skin-avatar');avatar.setAttribute('aria-label','3D-голова Minecraft');
      const model=document.createElement('div');model.className='skin-model';avatar.append(model);
      const view={model,headOnly:true};viewers.add(view);draw(view);}
  };
})();

(() => {
  'use strict';
  document.querySelectorAll('[data-vtc-review-form]').forEach(form=>form.addEventListener('submit',async event=>{
    event.preventDefault();if(!form.reportValidity())return;
    const button=form.querySelector('button'),status=form.querySelector('[role="status"]');button.disabled=true;
    try{
      const response=await fetch(form.dataset.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Elearning-CSRF':form.dataset.csrf},body:JSON.stringify({outcome:form.elements.outcome.value,comment:form.elements.comment.value})});
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'La relecture n’a pas pu être enregistrée.');
      status.textContent='Relecture enregistrée. Le stagiaire retrouvera votre retour à la prochaine ouverture de sa copie.';
    }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  }));
})();
